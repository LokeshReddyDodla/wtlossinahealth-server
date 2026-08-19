"""Notification Broker — the single delivery choke point.

Locks the policy decisions: tier→behavior, per-category patient-local budget,
mute with an unmutable CRITICAL tier, quiet hours, permission bypass. Real
broker logic; only the boundaries (Redis budget, DB mute, timezone, FCM) are
stubbed.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from lib.services.notifications import broker
from lib.services.notifications.policy import NotificationTier, policy_for


# ── policy registry ───────────────────────────────────────────────────────────


class TestPolicy:
    def test_tiers_are_correct(self):
        assert policy_for("medication_dose").tier is NotificationTier.CRITICAL
        assert policy_for("meal_logged").tier is NotificationTier.EVENT
        assert policy_for("proactive_insight").tier is NotificationTier.PROACTIVE
        assert policy_for("gamification").tier is NotificationTier.SOCIAL

    def test_critical_is_unmutable_unlimited_permission_bypassing(self):
        p = policy_for("medication_dose")
        assert p.mutable is False and p.daily_cap is None and p.bypass_permission is True
        assert p.respects_quiet_hours is False

    def test_event_unlimited_but_respects_permission(self):
        p = policy_for("meal_logged")
        assert p.daily_cap is None and p.respects_quiet_hours is False
        assert p.mutable is False and p.bypass_permission is False

    def test_social_capped_below_proactive(self):
        assert policy_for("gamification").daily_cap < policy_for("proactive_insight").daily_cap

    def test_unknown_category_defaults_to_safe_proactive(self):
        p = policy_for("some_future_type")
        assert p.tier is NotificationTier.PROACTIVE and p.mutable and p.daily_cap is not None

    def test_category_cap_override(self):
        assert policy_for("re_engagement").daily_cap == 1


# ── broker delivery decisions ─────────────────────────────────────────────────


@pytest.fixture
def stubs(monkeypatch):
    monkeypatch.setattr(broker, "_resolve_timezone", AsyncMock(return_value="Asia/Kolkata"))
    monkeypatch.setattr(broker, "_localize", AsyncMock(side_effect=lambda pid, t, b, bt: (t, b)))
    persist = AsyncMock(return_value="notif-1")
    monkeypatch.setattr(broker, "_persist", persist)
    fcm = AsyncMock(return_value=True)
    monkeypatch.setattr(broker, "_send_fcm", fcm)
    monkeypatch.setattr(broker, "_is_muted", AsyncMock(return_value=False))
    # quiet-hours check: default in-window (True)
    monkeypatch.setattr(
        "lib.ai_foundation.agents.proactive_monitor.scheduling.is_within_scan_window",
        lambda tz: True,
    )
    return {"persist": persist, "fcm": fcm}


def _deliver(category, **kw):
    return broker.deliver(
        "00000000-0000-4000-8000-000000000001",
        category=category, title="T", body="B",
        channel_key="health_insights", group_key="health_insights_group", **kw,
    )


class TestDelivery:
    @pytest.mark.asyncio
    async def test_event_bypasses_budget_and_quiet_hours(self, stubs, monkeypatch):
        # even with cap exhausted and outside window, an EVENT still sends
        monkeypatch.setattr(broker._budget, "under_cap", AsyncMock(return_value=False))
        monkeypatch.setattr(
            "lib.ai_foundation.agents.proactive_monitor.scheduling.is_within_scan_window",
            lambda tz: False,
        )
        r = await _deliver("meal_logged")
        assert r.delivered and r.reason == "sent"
        stubs["fcm"].assert_awaited_once()

    @pytest.mark.asyncio
    async def test_proactive_blocked_over_cap(self, stubs, monkeypatch):
        monkeypatch.setattr(broker._budget, "under_cap", AsyncMock(return_value=False))
        r = await _deliver("proactive_insight")
        assert not r.delivered and r.reason == "over_cap"
        stubs["fcm"].assert_not_awaited()

    @pytest.mark.asyncio
    async def test_proactive_blocked_in_quiet_hours(self, stubs, monkeypatch):
        monkeypatch.setattr(broker._budget, "under_cap", AsyncMock(return_value=True))
        monkeypatch.setattr(
            "lib.ai_foundation.agents.proactive_monitor.scheduling.is_within_scan_window",
            lambda tz: False,
        )
        r = await _deliver("proactive_insight")
        assert not r.delivered and r.reason == "quiet_hours"

    @pytest.mark.asyncio
    async def test_mutable_category_muted_is_dropped(self, stubs, monkeypatch):
        monkeypatch.setattr(broker, "_is_muted", AsyncMock(return_value=True))
        monkeypatch.setattr(broker._budget, "under_cap", AsyncMock(return_value=True))
        r = await _deliver("gamification")
        assert not r.delivered and r.reason == "muted"
        stubs["fcm"].assert_not_awaited()

    @pytest.mark.asyncio
    async def test_critical_ignores_mute_and_sends(self, stubs, monkeypatch):
        # even if a (bogus) mute row existed, CRITICAL is unmutable → never checked
        muted = AsyncMock(return_value=True)
        monkeypatch.setattr(broker, "_is_muted", muted)
        r = await _deliver("medication_dose")
        assert r.delivered and r.reason == "sent"
        muted.assert_not_awaited()  # unmutable tier never even looks

    @pytest.mark.asyncio
    async def test_proactive_records_budget_social_and_capped(self, stubs, monkeypatch):
        rec = AsyncMock()
        monkeypatch.setattr(broker._budget, "under_cap", AsyncMock(return_value=True))
        monkeypatch.setattr(broker._budget, "record_sent", rec)
        await _deliver("proactive_insight")
        rec.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_event_does_not_record_budget(self, stubs, monkeypatch):
        rec = AsyncMock()
        monkeypatch.setattr(broker._budget, "record_sent", rec)
        await _deliver("meal_logged")
        rec.assert_not_awaited()  # unlimited tier never counts

    @pytest.mark.asyncio
    async def test_prelocalized_skips_translation(self, stubs, monkeypatch):
        loc = AsyncMock(side_effect=lambda *a: ("X", "Y"))
        monkeypatch.setattr(broker, "_localize", loc)
        monkeypatch.setattr(broker._budget, "under_cap", AsyncMock(return_value=True))
        await _deliver("proactive_insight", prelocalized=True)
        loc.assert_not_awaited()


class TestMuteHonorsPolicy:
    """The mute API only exposes categories whose policy is actually mutable —
    the broker never checks mute for EVENT/CRITICAL, so offering those toggles
    would be a lie."""

    def test_only_mutable_categories_exposed(self):
        from rest_server.v1.patients.notification_preferences import _MUTABLE_CATEGORIES
        for c in _MUTABLE_CATEGORIES:
            assert policy_for(c).mutable is True
        for c in ("meal_logged", "medication_dose", "safety_alert", "cgm_threshold_crossed"):
            assert c not in _MUTABLE_CATEGORIES


class TestInsightsNotFiledAsNotifications:
    @pytest.mark.asyncio
    async def test_record_inbox_false_skips_persist(self, stubs, monkeypatch):
        monkeypatch.setattr(broker._budget, "under_cap", AsyncMock(return_value=True))
        r = await _deliver("proactive_insight", record_inbox=False)
        assert r.delivered  # still delivered via FCM
        stubs["persist"].assert_not_awaited()  # but never filed as a notification
        stubs["fcm"].assert_awaited_once()

    @pytest.mark.asyncio
    async def test_notifications_still_filed(self, stubs, monkeypatch):
        r = await _deliver("medication_dose")  # a real notification
        assert r.delivered
        stubs["persist"].assert_awaited_once()


class TestPersistOrderAndFcmPayload:
    @pytest.mark.asyncio
    async def test_persist_happens_before_fcm(self, stubs, monkeypatch):
        """A failed push must still leave an inbox row — so persist runs first."""
        order: list[str] = []
        stubs["persist"].side_effect = lambda *a, **k: order.append("persist") or "notif-1"
        stubs["fcm"].side_effect = lambda *a, **k: order.append("fcm") or True
        await _deliver("medication_dose")
        assert order == ["persist", "fcm"]

    @pytest.mark.asyncio
    async def test_fcm_payload_carries_id_category_and_passthrough(self, stubs):
        """Mobile deeplinks off notification_id + category; caller data is preserved."""
        await _deliver("medication_dose", data={"achievement_id": "abc"})
        payload = stubs["fcm"].call_args.args[5]
        assert payload["notification_id"] == "notif-1"
        assert payload["category"] == "medication_dose"
        assert payload["achievement_id"] == "abc"

    @pytest.mark.asyncio
    async def test_fcm_failure_is_swallowed_and_inbox_row_survives(self, stubs, monkeypatch):
        """FCM refusal on a permission-respecting tier: no raise, row kept, not sent."""
        monkeypatch.setattr(broker._budget, "under_cap", AsyncMock(return_value=True))
        stubs["fcm"].return_value = False
        r = await _deliver("proactive_insight")
        assert r.delivered is False and r.reason == "no_permission"
        assert r.notification_id == "notif-1"  # persisted before the failed push
        stubs["persist"].assert_awaited_once()
