"""Tests for SupportNotificationService.notify_queue.

The queue-agent fan-out has three correctness concerns:
1. existing chat participants must NOT be re-notified (they already got
   the regular participant fan-out from ChatNotificationService)
2. the sender must NOT receive their own message back as a queue ping
3. when there are no eligible recipients, we must short-circuit and not
   call ``enqueue_fcm_notification_async`` at all

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
    """Patch the async FCM enqueue. Records the call args."""
    enq = AsyncMock(return_value="job-1")
    monkeypatch.setattr(
        "lib.services.support.support_notification_service.enqueue_fcm_notification_async",
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
async def test_emit_to_queue_agents_skips_existing_participants(monkeypatch):
    """The whole point of this method: notify agents who AREN'T yet chat
    participants. Existing participants already got the regular
    notify_participants fan-out — re-emitting would be a wasted round-trip."""
    from lib.services import socketio_service as sio_mod
    from lib.services.support import (
        support_notification_service as mod,
    )

    chats_col = MagicMock()
    chats_col.find_one = AsyncMock(
        return_value={
            "_id": "chat-1",
            "participants": [{"id": "admin-A", "type": "admin"}],
        }
    )
    store = MagicMock()
    store.db = {"chats": chats_col}
    monkeypatch.setattr(mod, "get_mongo_store", lambda: store)

    fake_sio = MagicMock()
    fake_sio.emit = AsyncMock()
    monkeypatch.setattr(sio_mod, "sio", fake_sio)

    svc = SupportNotificationService()
    svc._fetch_queue_agents = AsyncMock(
        return_value=[("admin-A", "admin"), ("admin-B", "admin")]
    )

    await svc.emit_to_queue_agents(
        chat_id="chat-1",
        ticket={"scope": "product", "health_facility_id": None},
        event_key="chat_list_updated",
        data={"chat_id": "chat-1", "change": "status"},
    )

    rooms = [c.kwargs.get("room") for c in fake_sio.emit.await_args_list]
    assert rooms == ["admin-B"]
    assert "admin-A" not in rooms


@pytest.mark.asyncio
async def test_fetch_queue_agents_facility_uses_case_insensitive_role():
    """The auth dep accepts 'Support_Staff' (any casing). The queue SQL
    must too, otherwise a mixed-case CP can answer tickets but never gets
    pinged about new ones — silent inconsistency."""
    from unittest.mock import AsyncMock, MagicMock

    from sqlalchemy import func

    captured_wheres: list = []

    class FakeResult:
        def all(self):
            return []

    class FakeSession:
        async def execute(self, stmt):
            # Capture the SQL where-clause so we can introspect.
            captured_wheres.append(stmt)
            return FakeResult()

    class FakeSessionCtx:
        async def __aenter__(self):
            return FakeSession()

        async def __aexit__(self, *_):
            return False

    import lib.services.support.support_notification_service as mod

    def fake_session_factory():
        return FakeSessionCtx()

    original = mod.get_async_postgres_session
    mod.get_async_postgres_session = fake_session_factory
    try:
        svc = SupportNotificationService()
        # Use a valid UUID — _fetch_queue_agents binds it as a UUID column,
        # and we want the SQL compile to succeed so we can inspect the WHERE.
        await svc._fetch_queue_agents(
            scope="facility",
            health_facility_id="00000000-0000-0000-0000-000000000001",
        )
    finally:
        mod.get_async_postgres_session = original

    assert len(captured_wheres) == 1
    # Parameterized compile (no literal_binds) — we only care about the
    # text shape, not the bound values.
    compiled = str(captured_wheres[0].compile())
    assert "lower(" in compiled.lower()


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
