"""ChatMessagingService kind-aware behavior tests.

When ``chat.kind == "support"`` the FCM channel/group keys switch to the
support variants and a support queue fan-out fires alongside the usual
participant fan-out. When kind is anything else (incl. missing/legacy
chats), behavior must be identical to before the support feature was
added.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import lib.models  # noqa: F401,E402
from lib.models.patient import Patient  # noqa: F401,E402

from lib.services.chat.chat_messaging_service import (  # noqa: E402
    ChatMessagingService,
)


def _make_message():
    return SimpleNamespace(
        id="m-1",
        chat_id="chat-1",
        sender_id="patient-1",
        content="hello",
        metadata=SimpleNamespace(type="text"),
    )


# --- _create_notification_info ------------------------------------------


def test_notification_info_for_direct_chat_uses_chat_messages_channel():
    svc = ChatMessagingService()
    info = svc._create_notification_info(_make_message(), chat_kind="direct")
    assert info.channel_key == "chat_messages"
    assert info.group_key == "chat_group"
    assert info.title == "New Message"


def test_notification_info_for_group_chat_uses_chat_messages_channel():
    svc = ChatMessagingService()
    info = svc._create_notification_info(_make_message(), chat_kind="group")
    assert info.channel_key == "chat_messages"
    assert info.group_key == "chat_group"


def test_notification_info_for_support_chat_uses_support_channel():
    svc = ChatMessagingService()
    info = svc._create_notification_info(_make_message(), chat_kind="support")
    assert info.channel_key == "support_messages"
    assert info.group_key == "support_group"
    assert info.title == "Support Update"


def test_notification_info_default_kind_is_direct():
    """No kind argument == direct (covers legacy chat docs missing the
    field after the schema migration)."""
    svc = ChatMessagingService()
    info = svc._create_notification_info(_make_message())
    assert info.channel_key == "chat_messages"


# --- add_message dispatch -----------------------------------------------


@pytest.fixture
def messaging_svc(monkeypatch):
    """Build a ChatMessagingService whose persistence + notification side
    effects are mocked so we can inspect the branch logic."""
    svc = ChatMessagingService()
    svc.mongo_store = MagicMock()
    svc.mongo_store.db = {}

    # Inject a fake chats collection whose find_one returns a chat doc we
    # can override per-test.
    chats_collection = MagicMock()
    chats_collection.find_one = AsyncMock(return_value=None)
    chats_collection.update_one = AsyncMock()
    messages_collection = MagicMock()
    messages_collection.update_one = AsyncMock()
    # support_tickets lookup happens in add_message for kind=support
    # chats (spec item B — to embed ticket_id in the FCM data map).
    tickets_collection = MagicMock()
    tickets_collection.find_one = AsyncMock(
        return_value={"_id": "ticket-1"}
    )
    svc.mongo_store.db["chats"] = chats_collection
    svc.mongo_store.db["chat_messages"] = messages_collection
    svc.mongo_store.db["support_tickets"] = tickets_collection
    svc.mongo_store.insert_document = AsyncMock()

    # Stub notification path so it doesn't reach FCM.
    svc.notification_service = MagicMock()
    svc.notification_service.notify_participants = AsyncMock()
    svc.notification_service._get_notification_body = MagicMock(
        return_value="hello"
    )

    # Stub sender_profile enrichment so add_message doesn't hit PG.
    async def _passthrough_enrich(messages):
        return list(messages)

    monkeypatch.setattr(
        "lib.services.chat.chat_messaging_service.enrich_messages_with_sender_profiles",
        _passthrough_enrich,
    )

    return svc, chats_collection


@pytest.fixture
def fake_support_notification(monkeypatch):
    """Patch both SupportNotificationService and SupportTicketService at
    their import sites so the add_message support branch doesn't reach
    PG. The test only cares whether the support fan-out fires."""
    instances = []

    class FakeNotifSvc:
        def __init__(self):
            self.notify_queue = AsyncMock()
            instances.append(self)

    class FakeTicketSvc:
        def __init__(self):
            self.on_requester_message_in_support_chat = AsyncMock()

    monkeypatch.setattr(
        "lib.services.support.support_notification_service.SupportNotificationService",
        FakeNotifSvc,
    )
    monkeypatch.setattr(
        "lib.services.support.support_ticket_service.SupportTicketService",
        FakeTicketSvc,
    )
    return instances


def _build_message_create():
    from datetime import datetime

    from lib.schemas.chat_message import ChatMessageCreate, MetadataSchema

    return ChatMessageCreate(
        chat_id="chat-1",
        sender_id="patient-1",
        content="hello",
        timestamp=datetime.utcnow(),
        metadata=MetadataSchema(type="text", status="sent"),
        severity="low",
        is_flagged=False,
    )


@pytest.mark.asyncio
async def test_add_message_for_support_chat_triggers_queue_fanout(
    messaging_svc, fake_support_notification
):
    svc, chats_collection = messaging_svc
    chats_collection.find_one = AsyncMock(
        return_value={
            "_id": "chat-1",
            "kind": "support",
            "participants": [{"id": "patient-1", "type": "patient"}],
        }
    )

    await svc.add_message(_build_message_create())

    # Exactly one SupportNotificationService instance, exactly one call.
    assert len(fake_support_notification) == 1
    fake_support_notification[0].notify_queue.assert_awaited_once()


@pytest.mark.asyncio
async def test_add_message_for_direct_chat_does_not_fanout(
    messaging_svc, fake_support_notification
):
    svc, chats_collection = messaging_svc
    chats_collection.find_one = AsyncMock(
        return_value={
            "_id": "chat-1",
            "kind": "direct",
            "participants": [
                {"id": "patient-1", "type": "patient"},
                {"id": "cp-1", "type": "care_provider"},
            ],
        }
    )

    await svc.add_message(_build_message_create())

    # SupportNotificationService should never have been instantiated.
    assert fake_support_notification == []


@pytest.mark.asyncio
async def test_add_message_emits_chat_list_updated_new_message_alongside_received(
    messaging_svc, fake_support_notification
):
    """Unified event contract (spec A): every message send produces a
    ``chat_list_updated{change=new_message}`` row-patch event alongside
    the conversation-view ``new_message_received``. Sender excluded —
    they don't need their own row patch."""
    svc, chats_collection = messaging_svc
    chats_collection.find_one = AsyncMock(
        return_value={
            "_id": "chat-1",
            "kind": "direct",
            "participants": [
                {"id": "patient-1", "type": "patient"},
                {"id": "cp-1", "type": "care_provider"},
            ],
        }
    )

    await svc.add_message(_build_message_create())

    emits = svc.notification_service.notify_participants.await_args_list
    keys = [c.kwargs["message_key"] for c in emits]
    assert "new_message_received" in keys
    assert "chat_list_updated" in keys

    # Inspect the row-patch event specifically.
    list_emit = next(
        c
        for c in emits
        if c.kwargs["message_key"] == "chat_list_updated"
    )
    payload = list_emit.kwargs["data"]
    assert payload["chat_id"] == "chat-1"
    assert payload["change"] == "new_message"
    assert payload["last_message_preview"] == "hello"
    assert payload["last_message_sender_id"] == "patient-1"
    assert "last_message_at" in payload
    assert "last_message_id" in payload
    # Sender exclusion: they sent it, they don't need to be told.
    assert list_emit.kwargs["exclude_user_id"] == "patient-1"


@pytest.mark.asyncio
async def test_add_message_preview_is_sanitized(
    messaging_svc, fake_support_notification
):
    """Markdown formatting characters and whitespace runs are stripped
    server-side. Single source of truth — clients consume plain text."""
    from datetime import datetime

    from lib.schemas.chat_message import ChatMessageCreate, MetadataSchema

    svc, chats_collection = messaging_svc
    chats_collection.find_one = AsyncMock(
        return_value={
            "_id": "chat-1",
            "kind": "direct",
            "participants": [
                {"id": "patient-1", "type": "patient"},
                {"id": "cp-1", "type": "care_provider"},
            ],
        }
    )

    msg = ChatMessageCreate(
        chat_id="chat-1",
        sender_id="patient-1",
        content="*hello*   _world_\n\nfollowup",
        timestamp=datetime.utcnow(),
        metadata=MetadataSchema(type="text", status="sent"),
        severity="low",
        is_flagged=False,
    )
    await svc.add_message(msg)

    list_emit = next(
        c
        for c in svc.notification_service.notify_participants.await_args_list
        if c.kwargs["message_key"] == "chat_list_updated"
    )
    assert list_emit.kwargs["data"]["last_message_preview"] == (
        "hello world followup"
    )


@pytest.mark.asyncio
async def test_support_fcm_data_carries_chat_id_and_ticket_id(
    messaging_svc, fake_support_notification
):
    """Spec item B — support FCM pushes must carry chat_id + ticket_id in
    the data map so the Flutter notification controller can deep-link
    from the lockscreen tap directly to the thread."""
    svc, chats_collection = messaging_svc
    chats_collection.find_one = AsyncMock(
        return_value={
            "_id": "chat-1",
            "kind": "support",
            "participants": [{"id": "patient-1", "type": "patient"}],
        }
    )
    # Override the default tickets stub to return a specific id.
    svc.mongo_store.db["support_tickets"].find_one = AsyncMock(
        return_value={"_id": "ticket-42"}
    )

    await svc.add_message(_build_message_create())

    # Inspect the notification_info passed to the chat fan-out (the
    # first notify_participants call — for new_message_received).
    new_msg_emit = next(
        c
        for c in svc.notification_service.notify_participants.await_args_list
        if c.kwargs["message_key"] == "new_message_received"
    )
    info = new_msg_emit.kwargs["notification_info"]
    assert info.data == {
        "chat_id": "chat-1",
        "ticket_id": "ticket-42",
    }
    assert info.channel_key == "support_messages"


@pytest.mark.asyncio
async def test_non_support_fcm_data_is_empty(
    messaging_svc, fake_support_notification
):
    """For a direct chat, the FCM data map stays empty — no support
    routing info to embed."""
    svc, chats_collection = messaging_svc
    chats_collection.find_one = AsyncMock(
        return_value={
            "_id": "chat-1",
            "kind": "direct",
            "participants": [
                {"id": "patient-1", "type": "patient"},
                {"id": "cp-1", "type": "care_provider"},
            ],
        }
    )

    await svc.add_message(_build_message_create())

    new_msg_emit = next(
        c
        for c in svc.notification_service.notify_participants.await_args_list
        if c.kwargs["message_key"] == "new_message_received"
    )
    info = new_msg_emit.kwargs["notification_info"]
    assert info.data == {}
    assert info.channel_key == "chat_messages"


@pytest.mark.asyncio
async def test_support_fcm_data_empty_when_ticket_missing(
    messaging_svc, fake_support_notification
):
    """Defensive: if the support_tickets row can't be found for some
    reason, the FCM still goes out (channel key is right) but the data
    map is empty rather than embedding a nonsensical ticket_id."""
    svc, chats_collection = messaging_svc
    chats_collection.find_one = AsyncMock(
        return_value={
            "_id": "chat-1",
            "kind": "support",
            "participants": [{"id": "patient-1", "type": "patient"}],
        }
    )
    svc.mongo_store.db["support_tickets"].find_one = AsyncMock(
        return_value=None
    )

    await svc.add_message(_build_message_create())

    new_msg_emit = next(
        c
        for c in svc.notification_service.notify_participants.await_args_list
        if c.kwargs["message_key"] == "new_message_received"
    )
    info = new_msg_emit.kwargs["notification_info"]
    assert info.data == {}
    assert info.channel_key == "support_messages"


@pytest.mark.asyncio
async def test_add_message_for_legacy_chat_without_kind_defaults_direct(
    messaging_svc, fake_support_notification
):
    """Pre-existing chats predate the ``kind`` field; treat them as direct."""
    svc, chats_collection = messaging_svc
    chats_collection.find_one = AsyncMock(
        return_value={
            "_id": "chat-1",
            "participants": [{"id": "patient-1", "type": "patient"}],
        }
    )

    await svc.add_message(_build_message_create())
    assert fake_support_notification == []


# --- read-receipt fan-out excludes the triggering user ------------------


@pytest.mark.asyncio
async def test_mark_message_as_read_excludes_self_from_socket_fanout(
    messaging_svc,
):
    """The user who marks read shouldn't get their own ack echoed back."""
    svc, _ = messaging_svc
    # Stub the read-side helpers so we don't run real Mongo ops.
    svc._update_message_read_status = AsyncMock()
    svc._update_chat_unread_count = AsyncMock()

    await svc.mark_message_as_read(
        chat_id="chat-1", user_id="user-b", message_id="m-1"
    )

    svc.notification_service.notify_participants.assert_awaited_once()
    kwargs = svc.notification_service.notify_participants.await_args.kwargs
    assert kwargs["exclude_user_id"] == "user-b"


@pytest.mark.asyncio
async def test_mark_all_messages_as_read_excludes_self_from_socket_fanout(
    messaging_svc,
):
    svc, _ = messaging_svc
    svc._mark_all_messages_as_read_in_chat = AsyncMock()
    svc._update_chat_unread_count = AsyncMock()

    await svc.mark_all_messages_as_read(chat_id="chat-1", user_id="user-b")

    svc.notification_service.notify_participants.assert_awaited_once()
    kwargs = svc.notification_service.notify_participants.await_args.kwargs
    assert kwargs["exclude_user_id"] == "user-b"
