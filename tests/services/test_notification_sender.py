"""Tests for the central notification helper."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


@asynccontextmanager
async def _fake_session_ctx(session):
    yield session


def _fake_store(session):
    store = MagicMock()
    store.get_session = lambda: _fake_session_ctx(session)
    return store


def _patch_store(session):
    """Patch container.resolve(PostgresStore) to return a fake store."""
    from lib.core.container import container

    store = _fake_store(session)
    return patch.object(container, "resolve", return_value=store)


def _fake_session():
    """Fake AsyncSession: .add sets .id, commit/refresh are async no-ops."""
    session = MagicMock()
    session.commit = AsyncMock()

    async def _refresh(obj):
        obj.id = uuid4()

    session.refresh = AsyncMock(side_effect=_refresh)

    def _add(obj):
        session.last_added = obj

    session.add = MagicMock(side_effect=_add)
    return session


@pytest.mark.asyncio
async def test_persists_before_fcm():
    """DB commit must happen before FCM send."""
    from lib.services.notifications import sender

    session = _fake_session()
    calls: list[str] = []

    async def track_commit():
        calls.append("commit")

    session.commit.side_effect = track_commit

    mock_fcm = AsyncMock()

    async def track_send(**kwargs):
        calls.append("fcm")

    mock_fcm.send_fcm_notification_to_user_devices.side_effect = track_send

    with _patch_store(session), patch.object(
        sender, "FCMService", return_value=mock_fcm, create=True
    ):
        # FCMService is imported inside the function, so patch via module
        with patch("lib.services.fcm_service.FCMService", return_value=mock_fcm):
            await sender.record_and_send_notification(
                str(uuid4()),
                category="gamification",
                title="hi",
                body="body",
            )

    assert calls == ["commit", "fcm"], f"expected commit before fcm, got {calls}"


@pytest.mark.asyncio
async def test_fcm_failure_does_not_raise():
    """FCM exception must be swallowed; inbox row is the source of truth."""
    from lib.services.notifications import sender

    session = _fake_session()
    mock_fcm = AsyncMock()
    mock_fcm.send_fcm_notification_to_user_devices.side_effect = RuntimeError("boom")

    with _patch_store(session), patch(
        "lib.services.fcm_service.FCMService", return_value=mock_fcm
    ):
        notif_id = await sender.record_and_send_notification(
            str(uuid4()),
            category="gamification",
            title="level up",
            body="you hit level 5",
        )

    assert notif_id is not None
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_category_maps_to_expected_channel():
    """health_alert must route to the 'alerts' channel, gamification to 'gamification'."""
    from lib.services.notifications import sender

    cases = [
        ("gamification", "gamification", "gamification_group"),
        ("medication_lifecycle", "reminders", "reminder_group"),
        ("medication_refill", "reminders", "reminder_group"),
        ("medication_dose", "reminders", "reminder_group"),
        ("follow_up", "reminders", "reminder_group"),
    ]

    for category, expected_channel, expected_group in cases:
        session = _fake_session()
        mock_fcm = AsyncMock()
        with _patch_store(session), patch(
            "lib.services.fcm_service.FCMService", return_value=mock_fcm
        ):
            await sender.record_and_send_notification(
                str(uuid4()),
                category=category,  # type: ignore[arg-type]
                title="t",
                body="b",
            )

        kwargs = mock_fcm.send_fcm_notification_to_user_devices.call_args.kwargs
        assert kwargs["channel_key"] == expected_channel, category
        assert kwargs["group_key"] == expected_group, category


@pytest.mark.asyncio
async def test_fcm_payload_includes_notification_id_and_category():
    """FCM data payload must include notification_id + category so mobile can deeplink."""
    from lib.services.notifications import sender

    session = _fake_session()
    mock_fcm = AsyncMock()

    with _patch_store(session), patch(
        "lib.services.fcm_service.FCMService", return_value=mock_fcm
    ):
        await sender.record_and_send_notification(
            str(uuid4()),
            category="gamification",
            title="t",
            body="b",
            data={"achievement_id": "abc"},
        )

    kwargs = mock_fcm.send_fcm_notification_to_user_devices.call_args.kwargs
    assert "notification_id" in kwargs["data"]
    assert kwargs["data"]["category"] == "gamification"
    assert kwargs["data"]["achievement_id"] == "abc"
