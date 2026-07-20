"""The legacy notification helper is now a thin adapter over the broker.

Its only job is to map a legacy sender category to the broker's
(channel_key, group_key, broker_category) route and delegate. Delivery
policy (persist, FCM, budget, mute, quiet hours, payload) is the broker's
and is locked by tests/ai_foundation/test_notification_broker.py.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from lib.services.notifications import sender
from lib.services.notifications.broker import DeliveryResult


def _patch_deliver(notification_id=None):
    result = DeliveryResult(True, "sent", notification_id)
    return patch(
        "lib.services.notifications.broker.deliver",
        new=AsyncMock(return_value=result),
    )


@pytest.mark.asyncio
async def test_category_routes_to_expected_channel_group_and_broker_category():
    """Each legacy category maps to the right channel/group and broker category."""
    cases = [
        ("gamification", "gamification", "gamification_group", "gamification"),
        ("medication_lifecycle", "reminders", "reminder_group", "medication_lifecycle"),
        ("medication_refill", "reminders", "reminder_group", "refill_reminder"),
        ("medication_dose", "reminders", "reminder_group", "medication_dose"),
        ("follow_up", "reminders", "reminder_group", "follow_up_reminder"),
    ]
    for category, channel, group, broker_category in cases:
        with _patch_deliver() as deliver:
            await sender.record_and_send_notification(
                str(uuid4()), category=category, title="t", body="b",
            )
        kwargs = deliver.call_args.kwargs
        assert kwargs["channel_key"] == channel, category
        assert kwargs["group_key"] == group, category
        assert kwargs["category"] == broker_category, category


@pytest.mark.asyncio
async def test_returns_broker_notification_id_and_forwards_data():
    """The adapter returns the broker's inbox id and forwards caller data/severity."""
    nid = uuid4()
    with _patch_deliver(nid) as deliver:
        returned = await sender.record_and_send_notification(
            str(uuid4()),
            category="gamification",
            title="level up",
            body="you hit level 5",
            data={"achievement_id": "abc"},
            severity="info",
        )
    assert returned == nid
    kwargs = deliver.call_args.kwargs
    assert kwargs["data"] == {"achievement_id": "abc"}
    assert kwargs["severity"] == "info"


@pytest.mark.asyncio
async def test_skip_permission_check_maps_to_force():
    """skip_permission_check is a system send — the broker's force bypass."""
    with _patch_deliver() as deliver:
        await sender.record_and_send_notification(
            str(uuid4()), category="medication_dose", title="t", body="b",
            skip_permission_check=True,
        )
    assert deliver.call_args.kwargs["force"] is True
