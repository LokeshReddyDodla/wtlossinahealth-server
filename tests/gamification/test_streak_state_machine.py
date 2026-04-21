"""Exhaustive state-machine matrix for StreakService.process_streak.

Extends the 4 existing tests in test_streak_service.py with a parametrized
truth table covering all branch combinations of:

  state = (current_streak, last_active_date, streak_frozen_on, streak_freezes)
  input = (was_active_today, allow_break)

Outcomes covered:
- START / INCREMENT / EARN_FREEZE (every 7 days, capped at 3)
- RESET (gap too large, was_active=True but non-consecutive)
- ALREADY_PROCESSED (last_active_date == for_date)
- PENDING (was_active=False and allow_break=False)
- FREEZE (was_active=False, allow_break=True, freezes available)
- BROKEN (was_active=False, allow_break=True, no freezes)
- CONTINUE-VIA-FREEZE (frozen yesterday, active today)

Mocks _get_or_create_profile and _was_active so we can drive every state
combination deterministically with no DB.
"""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tests.gamification.helpers import FakeSession, load_module, make_module


# ── Module loader (stubs heavyweight deps) ──────────────────────────────────


def _load_streak(monkeypatch, name="streak_state_machine_test"):
    challenge_calls: list[dict] = []
    feed_calls: list[dict] = []

    class FakeChallengeService:
        async def update_participant_progress(self, **kwargs):
            challenge_calls.append(kwargs)

    class FakeFeedService:
        async def post_event(self, **kwargs):
            feed_calls.append(kwargs)

    class FakeContainer:
        def resolve(self, cls):
            cls_name = getattr(cls, "__name__", "")
            if "Challenge" in cls_name:
                return FakeChallengeService()
            return FakeFeedService()

    notif_calls: list[dict] = []

    async def fake_send_notification(_pid, **kwargs):
        notif_calls.append(kwargs)

    module = load_module(
        monkeypatch,
        "lib/services/gamification/streak_service.py",
        name,
        {
            "lib.core.container": make_module(
                "lib.core.container", container=FakeContainer(),
            ),
            "lib.services.gamification.challenge_service": make_module(
                "lib.services.gamification.challenge_service",
                ChallengeService=FakeChallengeService,
            ),
            "lib.services.gamification.feed_service": make_module(
                "lib.services.gamification.feed_service",
                FeedService=FakeFeedService,
            ),
            "lib.services.gamification.notifications": make_module(
                "lib.services.gamification.notifications",
                send_gamification_notification=fake_send_notification,
            ),
        },
    )
    module._challenge_calls = challenge_calls
    module._feed_calls = feed_calls
    module._notif_calls = notif_calls
    return module


def _make_service(monkeypatch, profile, was_active):
    module = _load_streak(monkeypatch)
    service = module.StreakService(postgres_store=None)

    async def fake_get_or_create_profile(_patient_id, _session):
        return profile

    async def fake_was_active(_patient_id, _for_date, _session):
        return was_active

    monkeypatch.setattr(service, "_get_or_create_profile", fake_get_or_create_profile)
    monkeypatch.setattr(service, "_was_active", fake_was_active)
    return service, module


def _profile(
    *,
    current_streak=0,
    longest_streak=0,
    last_active_date=None,
    streak_frozen_on=None,
    streak_freezes=0,
    streak_resets=0,
):
    return SimpleNamespace(
        current_streak=current_streak,
        longest_streak=longest_streak,
        last_active_date=last_active_date,
        streak_frozen_on=streak_frozen_on,
        streak_freezes=streak_freezes,
        streak_resets=streak_resets,
    )


TODAY = date(2026, 4, 15)
YESTERDAY = TODAY - timedelta(days=1)
TWO_DAYS_AGO = TODAY - timedelta(days=2)
THREE_DAYS_AGO = TODAY - timedelta(days=3)


# ── ALREADY_PROCESSED ───────────────────────────────────────────────────────


class TestAlreadyProcessed:
    @pytest.mark.asyncio
    async def test_returns_already_processed_when_last_active_equals_today(self, monkeypatch):
        prof = _profile(current_streak=5, last_active_date=TODAY)
        svc, _ = _make_service(monkeypatch, prof, was_active=True)
        result = await svc.process_streak(
            patient_id="p1", for_date=TODAY, postgres_session=FakeSession(),
        )
        assert result == {"action": "already_processed", "streak": 5}
        assert prof.current_streak == 5  # unchanged


# ── INCREMENT (was_active, consecutive) ─────────────────────────────────────


class TestIncrementConsecutive:
    @pytest.mark.asyncio
    async def test_first_active_day(self, monkeypatch):
        prof = _profile(current_streak=0, last_active_date=None)
        svc, _ = _make_service(monkeypatch, prof, was_active=True)
        result = await svc.process_streak(
            patient_id="p1", for_date=TODAY, postgres_session=FakeSession(),
        )
        assert result == {"action": "incremented", "streak": 1}
        assert prof.current_streak == 1
        assert prof.longest_streak == 1
        assert prof.last_active_date == TODAY

    @pytest.mark.asyncio
    async def test_consecutive_increments(self, monkeypatch):
        prof = _profile(current_streak=5, longest_streak=5, last_active_date=YESTERDAY)
        svc, _ = _make_service(monkeypatch, prof, was_active=True)
        result = await svc.process_streak(
            patient_id="p1", for_date=TODAY, postgres_session=FakeSession(),
        )
        assert result == {"action": "incremented", "streak": 6}
        assert prof.current_streak == 6
        assert prof.longest_streak == 6
        assert prof.last_active_date == TODAY
        assert prof.streak_frozen_on is None  # cleared

    @pytest.mark.asyncio
    async def test_longest_only_grows(self, monkeypatch):
        prof = _profile(current_streak=5, longest_streak=10, last_active_date=YESTERDAY)
        svc, _ = _make_service(monkeypatch, prof, was_active=True)
        await svc.process_streak(
            patient_id="p1", for_date=TODAY, postgres_session=FakeSession(),
        )
        assert prof.current_streak == 6
        assert prof.longest_streak == 10  # unchanged

    @pytest.mark.asyncio
    async def test_consecutive_via_freeze_bridge(self, monkeypatch):
        """Yesterday was frozen (used a freeze) — today's activity continues."""
        prof = _profile(
            current_streak=10,
            longest_streak=10,
            last_active_date=TWO_DAYS_AGO,  # gap day was yesterday → frozen
            streak_frozen_on=YESTERDAY,
            streak_freezes=1,
        )
        svc, _ = _make_service(monkeypatch, prof, was_active=True)
        result = await svc.process_streak(
            patient_id="p1", for_date=TODAY, postgres_session=FakeSession(),
        )
        assert result == {"action": "incremented", "streak": 11}


# ── RESET (was_active, gap too large) ───────────────────────────────────────


class TestResetAfterGap:
    @pytest.mark.asyncio
    async def test_active_after_gap_resets_to_one(self, monkeypatch):
        prof = _profile(
            current_streak=10, longest_streak=10, last_active_date=THREE_DAYS_AGO,
        )
        svc, _ = _make_service(monkeypatch, prof, was_active=True)
        result = await svc.process_streak(
            patient_id="p1", for_date=TODAY, postgres_session=FakeSession(),
        )
        # Gap is 3 days — too large, resets to 1 (per implementation)
        assert result == {"action": "incremented", "streak": 1}
        assert prof.current_streak == 1
        assert prof.longest_streak == 10  # preserved

    @pytest.mark.asyncio
    async def test_active_with_2day_gap_resets(self, monkeypatch):
        """2-day gap (last_active = day before yesterday) and no bridging freeze
        — resets to 1."""
        prof = _profile(
            current_streak=5, longest_streak=5, last_active_date=TWO_DAYS_AGO,
            streak_frozen_on=None,
        )
        svc, _ = _make_service(monkeypatch, prof, was_active=True)
        result = await svc.process_streak(
            patient_id="p1", for_date=TODAY, postgres_session=FakeSession(),
        )
        assert result["action"] == "incremented"
        assert prof.current_streak == 1


# ── EARN_FREEZE (every 7 days, capped at 3) ─────────────────────────────────


class TestEarnFreeze:
    @pytest.mark.parametrize(
        "starting_streak,starting_freezes,expected_freezes",
        [
            (6, 0, 1),    # → 7, earn first freeze
            (13, 1, 2),   # → 14, earn second
            (20, 2, 3),   # → 21, earn third (cap)
            (27, 3, 3),   # → 28, cap reached, no new freeze
            (34, 3, 3),   # → 35, still capped
            (5, 0, 0),    # → 6, not multiple of 7
            (8, 1, 1),    # → 9, not multiple of 7
        ],
    )
    @pytest.mark.asyncio
    async def test_freeze_earned_at_multiples_of_seven(
        self, monkeypatch, starting_streak, starting_freezes, expected_freezes,
    ):
        prof = _profile(
            current_streak=starting_streak,
            longest_streak=starting_streak,
            last_active_date=YESTERDAY,
            streak_freezes=starting_freezes,
        )
        svc, module = _make_service(monkeypatch, prof, was_active=True)
        await svc.process_streak(
            patient_id="p1", for_date=TODAY, postgres_session=FakeSession(),
        )
        assert prof.streak_freezes == expected_freezes

        # Notification sent only when freeze actually earned
        if expected_freezes > starting_freezes:
            assert any(
                "freeze" in (c.get("title") or "").lower()
                for c in module._notif_calls
            )


# ── PENDING (was_active=False, allow_break=False) ───────────────────────────


class TestPending:
    @pytest.mark.asyncio
    async def test_pending_when_no_activity_and_break_disallowed(self, monkeypatch):
        prof = _profile(current_streak=5, last_active_date=YESTERDAY)
        svc, _ = _make_service(monkeypatch, prof, was_active=False)
        result = await svc.process_streak(
            patient_id="p1", for_date=TODAY, allow_break=False,
            postgres_session=FakeSession(),
        )
        assert result == {"action": "pending", "streak": 5}
        # No mutation
        assert prof.current_streak == 5
        assert prof.last_active_date == YESTERDAY


# ── FREEZE (was_active=False, allow_break=True, freezes available) ──────────


class TestFreeze:
    @pytest.mark.asyncio
    async def test_freeze_used_when_inactive_with_freezes(self, monkeypatch):
        prof = _profile(
            current_streak=5, longest_streak=5,
            last_active_date=YESTERDAY, streak_freezes=2,
        )
        svc, _ = _make_service(monkeypatch, prof, was_active=False)
        result = await svc.process_streak(
            patient_id="p1", for_date=TODAY, postgres_session=FakeSession(),
        )
        assert result == {"action": "frozen", "streak": 5, "freezes_remaining": 1}
        assert prof.streak_freezes == 1
        assert prof.streak_frozen_on == TODAY
        assert prof.current_streak == 5  # preserved

    @pytest.mark.asyncio
    async def test_freeze_notification_sent(self, monkeypatch):
        prof = _profile(current_streak=10, last_active_date=YESTERDAY, streak_freezes=1)
        svc, module = _make_service(monkeypatch, prof, was_active=False)
        await svc.process_streak(
            patient_id="p1", for_date=TODAY, postgres_session=FakeSession(),
        )
        assert any(
            (c.get("data") or {}).get("event_type") == "streak_freeze_used"
            for c in module._notif_calls
        )

    @pytest.mark.asyncio
    async def test_no_freeze_when_streak_zero_even_with_freezes(self, monkeypatch):
        """Edge: freezes available but no streak — falls through to BROKEN."""
        prof = _profile(current_streak=0, last_active_date=None, streak_freezes=3)
        svc, _ = _make_service(monkeypatch, prof, was_active=False)
        result = await svc.process_streak(
            patient_id="p1", for_date=TODAY, postgres_session=FakeSession(),
        )
        assert result["action"] == "broken"
        assert prof.streak_freezes == 3  # not consumed
        assert prof.streak_resets == 0  # was 0 → no increment

    @pytest.mark.asyncio
    async def test_freeze_is_idempotent_for_same_date(self, monkeypatch):
        """Processing the same missed date twice must not consume two freezes.

        This can happen when a manual use_freeze runs for a date and then the
        nightly cron re-processes it, or when the cron itself re-runs.
        """
        prof = _profile(
            current_streak=5, longest_streak=5,
            last_active_date=YESTERDAY, streak_freezes=2,
        )
        svc, module = _make_service(monkeypatch, prof, was_active=False)

        # First run — freeze consumed
        r1 = await svc.process_streak(
            patient_id="p1", for_date=TODAY, postgres_session=FakeSession(),
        )
        assert r1["action"] == "frozen"
        assert prof.streak_freezes == 1
        assert prof.streak_frozen_on == TODAY

        # Second run for the SAME date — must not consume another freeze
        r2 = await svc.process_streak(
            patient_id="p1", for_date=TODAY, postgres_session=FakeSession(),
        )
        assert r2["action"] == "frozen"
        assert prof.streak_freezes == 1  # unchanged
        assert prof.streak_frozen_on == TODAY
        assert prof.current_streak == 5


# ── BROKEN (was_active=False, allow_break=True, no freezes) ─────────────────


class TestBroken:
    @pytest.mark.asyncio
    async def test_streak_broken_when_inactive_no_freezes(self, monkeypatch):
        prof = _profile(
            current_streak=10, longest_streak=10,
            last_active_date=YESTERDAY, streak_freezes=0, streak_resets=0,
        )
        svc, _ = _make_service(monkeypatch, prof, was_active=False)
        result = await svc.process_streak(
            patient_id="p1", for_date=TODAY, postgres_session=FakeSession(),
        )
        assert result == {"action": "broken", "old_streak": 10, "streak": 0}
        assert prof.current_streak == 0
        assert prof.streak_resets == 1
        assert prof.longest_streak == 10  # preserved
        assert prof.streak_frozen_on is None

    @pytest.mark.asyncio
    async def test_zero_streak_inactive_does_not_increment_resets(self, monkeypatch):
        prof = _profile(current_streak=0, streak_resets=5)
        svc, _ = _make_service(monkeypatch, prof, was_active=False)
        result = await svc.process_streak(
            patient_id="p1", for_date=TODAY, postgres_session=FakeSession(),
        )
        assert result["action"] == "broken"
        assert prof.streak_resets == 5  # unchanged because old_streak was 0


# ── Streak milestone feed events ────────────────────────────────────────────


class TestStreakMilestones:
    @pytest.mark.parametrize("milestone_streak", [7, 14, 30, 60, 90])
    @pytest.mark.asyncio
    async def test_milestone_posts_feed_event(self, monkeypatch, milestone_streak):
        prof = _profile(
            current_streak=milestone_streak - 1,
            longest_streak=milestone_streak - 1,
            last_active_date=YESTERDAY,
        )
        svc, module = _make_service(monkeypatch, prof, was_active=True)
        await svc.process_streak(
            patient_id="p1", for_date=TODAY, postgres_session=FakeSession(),
        )
        # Feed event posted with streak milestone
        milestone_events = [
            e for e in module._feed_calls
            if e.get("event_type") == "streak_milestone"
        ]
        assert len(milestone_events) == 1
        assert milestone_events[0]["event_data"]["streak"] == milestone_streak

    @pytest.mark.parametrize("non_milestone_streak", [2, 5, 8, 13, 21, 28, 50])
    @pytest.mark.asyncio
    async def test_non_milestone_no_feed_event(self, monkeypatch, non_milestone_streak):
        prof = _profile(
            current_streak=non_milestone_streak - 1,
            longest_streak=non_milestone_streak - 1,
            last_active_date=YESTERDAY,
        )
        svc, module = _make_service(monkeypatch, prof, was_active=True)
        await svc.process_streak(
            patient_id="p1", for_date=TODAY, postgres_session=FakeSession(),
        )
        milestone_events = [
            e for e in module._feed_calls
            if e.get("event_type") == "streak_milestone"
        ]
        assert milestone_events == []


# ── Challenge metric integration ────────────────────────────────────────────


class TestChallengeMetricUpdate:
    @pytest.mark.asyncio
    async def test_increment_streak_pushes_challenge_metric(self, monkeypatch):
        prof = _profile(current_streak=5, last_active_date=YESTERDAY)
        svc, module = _make_service(monkeypatch, prof, was_active=True)
        await svc.process_streak(
            patient_id="p1", for_date=TODAY, postgres_session=FakeSession(),
        )
        assert module._challenge_calls == [
            {"patient_id": "p1", "metric_type": "streak_days", "increment": 1.0},
        ]

    @pytest.mark.asyncio
    async def test_freeze_does_not_push_metric(self, monkeypatch):
        prof = _profile(current_streak=5, last_active_date=YESTERDAY, streak_freezes=1)
        svc, module = _make_service(monkeypatch, prof, was_active=False)
        await svc.process_streak(
            patient_id="p1", for_date=TODAY, postgres_session=FakeSession(),
        )
        # No challenge metric update on freeze
        assert module._challenge_calls == []

    @pytest.mark.asyncio
    async def test_break_does_not_push_metric(self, monkeypatch):
        prof = _profile(current_streak=5, last_active_date=YESTERDAY, streak_freezes=0)
        svc, module = _make_service(monkeypatch, prof, was_active=False)
        await svc.process_streak(
            patient_id="p1", for_date=TODAY, postgres_session=FakeSession(),
        )
        assert module._challenge_calls == []


# ── use_freeze ──────────────────────────────────────────────────────────────


class TestUseFreezeManual:
    @pytest.mark.asyncio
    async def test_rejects_already_applied_for_date(self, monkeypatch):
        module = _load_streak(monkeypatch, "use_freeze_test_already")
        svc = module.StreakService(postgres_store=None)
        prof = _profile(
            current_streak=5, streak_freezes=2, streak_frozen_on=date(2026, 4, 14),
        )

        async def fake_get(_pid, _s):
            return prof
        monkeypatch.setattr(svc, "_get_or_create_profile", fake_get)

        with pytest.raises(ValueError, match="Freeze already applied"):
            await svc.use_freeze(
                patient_id=None, freeze_date=date(2026, 4, 14),
                postgres_session=FakeSession(),
            )
        assert prof.streak_freezes == 2  # unchanged

    @pytest.mark.asyncio
    async def test_decrements_and_sets_date_on_success(self, monkeypatch):
        module = _load_streak(monkeypatch, "use_freeze_test_success")
        svc = module.StreakService(postgres_store=None)
        prof = _profile(current_streak=5, streak_freezes=3, streak_frozen_on=None)

        async def fake_get(_pid, _s):
            return prof
        monkeypatch.setattr(svc, "_get_or_create_profile", fake_get)

        result = await svc.use_freeze(
            patient_id=None, freeze_date=date(2026, 4, 15),
            postgres_session=FakeSession(),
        )
        assert result is prof
        assert prof.streak_freezes == 2
        assert prof.streak_frozen_on == date(2026, 4, 15)


# ── Buddy streak (process_buddy_streaks) ────────────────────────────────────


class TestBuddyStreaks:
    """Lock the buddy_streak update logic for active buddy pairs."""

    @pytest.mark.asyncio
    async def test_both_active_increments_buddy_streak(self, monkeypatch):
        module = _load_streak(monkeypatch, "buddy_streak_both_active")
        svc = module.StreakService(postgres_store=None)
        my_id, other_id = "p1", "p2"
        buddy = SimpleNamespace(
            requester_id=my_id, accepter_id=other_id, status="active",
            buddy_streak=4, buddy_streak_longest=4,
            last_both_active=date(2026, 4, 13),
        )

        # First execute = list buddies
        # Subsequent _was_active queries are mocked
        session = FakeSession(results=[
            SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [buddy])),
        ])

        async def fake_was_active(pid, _for_date, _session):
            return True
        monkeypatch.setattr(svc, "_was_active", fake_was_active)

        await svc.process_buddy_streaks(
            patient_id=my_id, for_date=TODAY, postgres_session=session,
        )
        assert buddy.buddy_streak == 5
        assert buddy.buddy_streak_longest == 5
        assert buddy.last_both_active == TODAY

    @pytest.mark.asyncio
    async def test_one_inactive_breaks_buddy_streak(self, monkeypatch):
        module = _load_streak(monkeypatch, "buddy_streak_one_inactive")
        svc = module.StreakService(postgres_store=None)
        my_id, other_id = "p1", "p2"
        buddy = SimpleNamespace(
            requester_id=my_id, accepter_id=other_id, status="active",
            buddy_streak=4, buddy_streak_longest=4,
            last_both_active=date(2026, 4, 13),
        )
        session = FakeSession(results=[
            SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [buddy])),
        ])

        # I'm active, other isn't
        call_results = {my_id: True, other_id: False}

        async def fake_was_active(pid, _for_date, _session):
            return call_results[pid]
        monkeypatch.setattr(svc, "_was_active", fake_was_active)

        await svc.process_buddy_streaks(
            patient_id=my_id, for_date=TODAY, postgres_session=session,
        )
        assert buddy.buddy_streak == 0
        assert buddy.buddy_streak_longest == 4  # preserved
        assert buddy.last_both_active == date(2026, 4, 13)  # not updated

    @pytest.mark.asyncio
    async def test_skip_already_processed_for_date(self, monkeypatch):
        module = _load_streak(monkeypatch, "buddy_streak_already")
        svc = module.StreakService(postgres_store=None)
        buddy = SimpleNamespace(
            requester_id="p1", accepter_id="p2", status="active",
            buddy_streak=4, buddy_streak_longest=4,
            last_both_active=TODAY,
        )
        session = FakeSession(results=[
            SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [buddy])),
        ])

        async def fake_was_active(_pid, _for_date, _session):
            return True
        monkeypatch.setattr(svc, "_was_active", fake_was_active)

        await svc.process_buddy_streaks(
            patient_id="p1", for_date=TODAY, postgres_session=session,
        )
        assert buddy.buddy_streak == 4  # unchanged

    @pytest.mark.asyncio
    async def test_no_break_when_allow_break_false(self, monkeypatch):
        module = _load_streak(monkeypatch, "buddy_streak_no_break")
        svc = module.StreakService(postgres_store=None)
        buddy = SimpleNamespace(
            requester_id="p1", accepter_id="p2", status="active",
            buddy_streak=4, buddy_streak_longest=4,
            last_both_active=date(2026, 4, 13),
        )
        session = FakeSession(results=[
            SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [buddy])),
        ])

        async def fake_was_active(pid, _for_date, _session):
            return pid == "p1"  # I'm active, buddy isn't
        monkeypatch.setattr(svc, "_was_active", fake_was_active)

        await svc.process_buddy_streaks(
            patient_id="p1", for_date=TODAY,
            allow_break=False, postgres_session=session,
        )
        assert buddy.buddy_streak == 4  # not broken when allow_break=False
