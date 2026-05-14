"""Tests for SupportNotificationService.notify_queue.

The queue-agent fan-out has three correctness concerns:
1. existing chat participants must NOT be re-notified (they already got
   the regular participant fan-out from ChatNotificationService)
2. the sender must NOT receive their own message back as a queue ping
3. when there are no eligible recipients, we must short-circuit and not
   call ``enqueue_fcm_notification_sync`` at all

The PG side (`_fetch_queue_agents`) is stubbed on the instance so we can
test the filter logic without spinning up a session — that SQL is plain
enough that it doesn't need its own unit test.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import lib.models  # noqa: F401,E402
from lib.models.patient import Patient  # noqa: F401,E402

from lib.services.support.support_notification_service import (  # noqa: E402
    SupportNotificationService,
)


@pytest.fixture
def fake_mongo(monkeypatch):
    """Patch the mongo_store accessor at the module level so ``notify_queue``
    finds our ticket stub."""
    collection = MagicMock()
    collection.find_one = AsyncMock(return_value=None)
    store = MagicMock()
    store.db = {"support_tickets": collection}

    monkeypatch.setattr(
        "lib.services.support.support_notification_service.get_mongo_store",
        lambda: store,
    )
    return collection


@pytest.fixture
def fake_enqueue(monkeypatch):
    """Patch the sync FCM enqueue. Records the call args."""
    enq = MagicMock(return_value="job-1")
    monkeypatch.setattr(
        "lib.services.support.support_notification_service.enqueue_fcm_notification_sync",
        enq,
    )
    return enq


def _make_info():
    """Minimal FCMNotificationInfo-shaped object with a .dict() method."""
    info = MagicMock()
    info.dict = MagicMock(
        return_value={
            "title": "Support Update",
            "channel_key": "support_messages",
        }
    )
    return info


@pytest.mark.asyncio
async def test_notify_queue_returns_when_no_ticket(fake_mongo, fake_enqueue):
    """Defensive: if the ticket row isn't there, we log and bail — not
    a 500."""
    fake_mongo.find_one = AsyncMock(return_value=None)

    svc = SupportNotificationService()
    svc._fetch_queue_agents = AsyncMock(return_value=[])

    await svc.notify_queue(
        chat={"_id": "chat-1", "participants": []},
        message={"_id": "m-1"},
        sender_id="patient-1",
        notification_info=_make_info(),
    )

    fake_enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_notify_queue_short_circuits_when_no_eligible_recipients(
    fake_mongo, fake_enqueue
):
    fake_mongo.find_one = AsyncMock(
        return_value={"_id": "t-1", "scope": "product"}
    )
    svc = SupportNotificationService()
    svc._fetch_queue_agents = AsyncMock(return_value=[])  # no admins

    await svc.notify_queue(
        chat={"_id": "chat-1", "participants": []},
        message={"_id": "m-1"},
        sender_id="patient-1",
        notification_info=_make_info(),
    )
    fake_enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_notify_queue_excludes_existing_participants(
    fake_mongo, fake_enqueue
):
    """An agent who has already joined the chat already received the
    regular fan-out — don't double-notify them."""
    fake_mongo.find_one = AsyncMock(
        return_value={"_id": "t-1", "scope": "product"}
    )
    svc = SupportNotificationService()
    svc._fetch_queue_agents = AsyncMock(
        return_value=[("admin-A", "admin"), ("admin-B", "admin")]
    )

    await svc.notify_queue(
        chat={
            "_id": "chat-1",
            "participants": [
                {"id": "patient-1", "type": "patient"},
                {"id": "admin-A", "type": "admin"},
            ],
        },
        message={"_id": "m-1"},
        sender_id="patient-1",
        notification_info=_make_info(),
    )

    fake_enqueue.assert_called_once()
    recipients = fake_enqueue.call_args.kwargs["participants"]
    assert recipients == [{"id": "admin-B", "type": "admin"}]


@pytest.mark.asyncio
async def test_notify_queue_excludes_sender(fake_mongo, fake_enqueue):
    """Edge: an agent who is *also* the sender (e.g. another admin
    replied) shouldn't get their own push."""
    fake_mongo.find_one = AsyncMock(
        return_value={"_id": "t-1", "scope": "product"}
    )
    svc = SupportNotificationService()
    svc._fetch_queue_agents = AsyncMock(
        return_value=[("admin-A", "admin"), ("admin-B", "admin")]
    )

    await svc.notify_queue(
        chat={"_id": "chat-1", "participants": []},
        message={"_id": "m-1"},
        sender_id="admin-A",
        notification_info=_make_info(),
    )

    fake_enqueue.assert_called_once()
    recipients = fake_enqueue.call_args.kwargs["participants"]
    assert recipients == [{"id": "admin-B", "type": "admin"}]


@pytest.mark.asyncio
async def test_notify_queue_passes_facility_id_to_agent_lookup(
    fake_mongo, fake_enqueue
):
    """For facility-scoped tickets, the facility id from the ticket doc
    must reach the agent lookup — that's how routing works."""
    fake_mongo.find_one = AsyncMock(
        return_value={
            "_id": "t-1",
            "scope": "facility",
            "health_facility_id": "f-42",
        }
    )
    svc = SupportNotificationService()
    svc._fetch_queue_agents = AsyncMock(
        return_value=[("cp-1", "care_provider")]
    )

    await svc.notify_queue(
        chat={"_id": "chat-1", "participants": []},
        message={"_id": "m-1"},
        sender_id="patient-1",
        notification_info=_make_info(),
    )

    svc._fetch_queue_agents.assert_awaited_once_with(
        scope="facility", health_facility_id="f-42"
    )


@pytest.mark.asyncio
async def test_notify_queue_forwards_notification_info_dict(
    fake_mongo, fake_enqueue
):
    fake_mongo.find_one = AsyncMock(
        return_value={"_id": "t-1", "scope": "product"}
    )
    info = _make_info()
    svc = SupportNotificationService()
    svc._fetch_queue_agents = AsyncMock(
        return_value=[("admin-A", "admin")]
    )

    await svc.notify_queue(
        chat={"_id": "chat-1", "participants": []},
        message={"_id": "m-1"},
        sender_id="patient-1",
        notification_info=info,
    )

    fake_enqueue.assert_called_once()
    assert (
        fake_enqueue.call_args.kwargs["notification_info"]
        == info.dict.return_value
    )
