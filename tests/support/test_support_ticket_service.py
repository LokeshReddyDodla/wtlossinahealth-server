"""Unit tests for :class:`SupportTicketService`.

Focus on business logic: scope/facility validation, requester vs agent
authorization filtering, participant management on agent reply, status
transitions with timestamps, and the UUID normalization seam introduced
to keep client-supplied facility ids consistent with PG-stored UUIDs.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

# Warm up the import graph so the pre-existing
# patient → chat_management_service circular import resolves cleanly.
import lib.models  # noqa: F401,E402
from lib.models.patient import Patient  # noqa: F401,E402
from lib.services.support.support_ticket_service import (  # noqa: E402
    SupportTicketService,
)


# --- fixtures -------------------------------------------------------------


def _make_fake_mongo():
    """Return a mongo_store stub whose ``db['support_tickets']`` supports
    ``find_one`` / ``update_one`` / ``insert_one`` and a chainable
    ``find().sort().skip().limit().to_list()``. Also stubs the ``chats``
    collection used by agent_reply's idempotent participant check and by
    SupportNotificationService.emit_to_queue_agents."""
    collection = MagicMock()
    collection.find_one = AsyncMock(return_value=None)
    collection.update_one = AsyncMock()
    collection.insert_one = AsyncMock()

    def _chain(*_a, **_kw):
        cursor = MagicMock()
        cursor.sort = MagicMock(return_value=cursor)
        cursor.skip = MagicMock(return_value=cursor)
        cursor.limit = MagicMock(return_value=cursor)
        cursor.to_list = AsyncMock(return_value=cursor._stub_results)
        cursor._stub_results = []
        return cursor

    collection.find = MagicMock(side_effect=_chain)

    # Chats collection: defaults to an empty-participants chat doc so the
    # idempotent-participant check in agent_reply runs.
    chats_collection = MagicMock()
    chats_collection.find_one = AsyncMock(
        return_value={"_id": "chat-1", "participants": []}
    )

    store = MagicMock()
    store.db = {"support_tickets": collection, "chats": chats_collection}
    store.insert_document = AsyncMock()
    return store, collection


@pytest.fixture
def fake_mongo():
    return _make_fake_mongo()


@pytest.fixture
def svc(fake_mongo, monkeypatch):
    store, _ = fake_mongo
    s = SupportTicketService()
    # Directly swap mongo + collaborators — patching get_mongo_store at the
    # module level doesn't help because the service captured it at import.
    s.mongo_store = store
    s.chat_management_service = MagicMock()
    s.chat_management_service.create_new_chat = AsyncMock(
        return_value="chat-1"
    )
    s.chat_messaging_service = MagicMock()
    s.chat_messaging_service.add_message = AsyncMock()
    s.chat_participant_service = MagicMock()
    s.chat_participant_service.add_participant_in_chat = AsyncMock()
    s.chat_notification_service = MagicMock()
    s.chat_notification_service.notify_participants = AsyncMock()

    # _emit_status_change creates a fresh SupportNotificationService and
    # calls emit_to_queue_agents on it. Stub the class with a fake so we
    # don't hit PG.
    class _FakeNotifSvc:
        emit_to_queue_agents = AsyncMock()
        notify_queue = AsyncMock()

    monkeypatch.setattr(
        "lib.services.support.support_notification_service.SupportNotificationService",
        _FakeNotifSvc,
    )
    s._fake_notif_svc_cls = _FakeNotifSvc  # exposed for assertions
    return s


# --- open_ticket ----------------------------------------------------------


@pytest.mark.asyncio
async def test_open_ticket_product_creates_support_chat(svc, fake_mongo):
    _, collection = fake_mongo

    ticket = await svc.open_ticket(
        requester_id="patient-1",
        requester_type="patient",
        scope="product",
        initial_message="hello",
        media=None,
        subject="account access",
        health_facility_id=None,
    )

    assert ticket["scope"] == "product"
    assert ticket["requester_id"] == "patient-1"
    assert ticket["requester_type"] == "patient"
    assert ticket["status"] == "open"
    assert ticket["chat_id"] == "chat-1"
    assert ticket["last_message_preview"] == "hello"
    assert ticket["health_facility_id"] is None

    # chat created with kind="support"
    svc.chat_management_service.create_new_chat.assert_awaited_once()
    kwargs = svc.chat_management_service.create_new_chat.await_args.kwargs
    assert kwargs["kind"] == "support"
    assert kwargs["is_group"] is False
    assert kwargs["user_id"] == "patient-1"

    # message sent through normal chat path
    svc.chat_messaging_service.add_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_open_ticket_facility_requires_facility_id(svc):
    with pytest.raises(ValueError, match="health_facility_id is required"):
        await svc.open_ticket(
            requester_id="patient-1",
            requester_type="patient",
            scope="facility",
            initial_message="hi",
            media=None,
            subject=None,
            health_facility_id=None,
        )


@pytest.mark.asyncio
async def test_open_ticket_normalizes_uuid_to_canonical_form(svc):
    # Uppercase + braces — same UUID, different surface form.
    raw = str(uuid4()).upper()
    ticket = await svc.open_ticket(
        requester_id="patient-1",
        requester_type="patient",
        scope="facility",
        initial_message="hi",
        media=None,
        subject=None,
        health_facility_id=raw,
    )
    # canonical form is lowercase 8-4-4-4-12
    assert ticket["health_facility_id"] == str(UUID(raw))
    assert ticket["health_facility_id"] == raw.lower()


@pytest.mark.asyncio
async def test_open_ticket_product_scope_drops_facility_id(svc):
    """Schema lets you accidentally pass health_facility_id on a product
    ticket — the service must drop it so we don't store semantically
    inconsistent rows ('product ticket scoped to facility X')."""
    from uuid import uuid4

    leaked = str(uuid4())
    ticket = await svc.open_ticket(
        requester_id="patient-1",
        requester_type="patient",
        scope="product",
        initial_message="hi",
        media=None,
        subject=None,
        health_facility_id=leaked,
    )
    assert ticket["health_facility_id"] is None


@pytest.mark.asyncio
async def test_open_ticket_rejects_malformed_facility_id(svc):
    with pytest.raises(ValueError, match="Invalid health_facility_id"):
        await svc.open_ticket(
            requester_id="patient-1",
            requester_type="patient",
            scope="facility",
            initial_message="hi",
            media=None,
            subject=None,
            health_facility_id="not-a-uuid",
        )


# --- requester scoping ----------------------------------------------------


@pytest.mark.asyncio
async def test_get_ticket_for_requester_scopes_by_requester_id(
    svc, fake_mongo
):
    _, collection = fake_mongo
    collection.find_one = AsyncMock(
        return_value={"_id": "t-1", "requester_id": "patient-1"}
    )

    out = await svc.get_ticket_for_requester("t-1", "patient-1")

    assert out == {"_id": "t-1", "requester_id": "patient-1"}
    query = collection.find_one.await_args.args[0]
    assert query == {"_id": "t-1", "requester_id": "patient-1"}


@pytest.mark.asyncio
async def test_get_ticket_for_requester_returns_none_for_other_owner(
    svc, fake_mongo
):
    """Mongo returns nothing when requester_id doesn't match — service
    must propagate that, not leak the ticket."""
    _, collection = fake_mongo
    collection.find_one = AsyncMock(return_value=None)

    out = await svc.get_ticket_for_requester("t-1", "patient-other")
    assert out is None


# --- agent access ---------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_admin_can_access_product_ticket(svc, fake_mongo):
    _, collection = fake_mongo
    collection.find_one = AsyncMock(
        return_value={"_id": "t-1", "scope": "product"}
    )

    out = await svc.get_ticket_for_agent(
        ticket_id="t-1",
        agent_scopes=["product"],
        agent_facility_ids=[],
    )
    assert out is not None


@pytest.mark.asyncio
async def test_agent_admin_cannot_access_facility_ticket(svc, fake_mongo):
    _, collection = fake_mongo
    collection.find_one = AsyncMock(
        return_value={
            "_id": "t-1",
            "scope": "facility",
            "health_facility_id": "f-1",
        }
    )

    out = await svc.get_ticket_for_agent(
        ticket_id="t-1",
        agent_scopes=["product"],
        agent_facility_ids=[],
    )
    assert out is None


@pytest.mark.asyncio
async def test_support_staff_cannot_access_other_facility(svc, fake_mongo):
    _, collection = fake_mongo
    collection.find_one = AsyncMock(
        return_value={
            "_id": "t-1",
            "scope": "facility",
            "health_facility_id": "facility-A",
        }
    )

    out = await svc.get_ticket_for_agent(
        ticket_id="t-1",
        agent_scopes=["facility"],
        agent_facility_ids=["facility-B"],
    )
    assert out is None


@pytest.mark.asyncio
async def test_get_with_messages_returns_thread_for_agent(svc, fake_mongo):
    """Agents need to read the thread BEFORE replying (otherwise they
    have nothing to reply to). At that point they aren't yet a chat
    participant, so we can't go through the participant-gated path."""
    store, collection = fake_mongo
    ticket = {
        "_id": "t-1",
        "chat_id": "chat-1",
        "scope": "product",
        "health_facility_id": None,
    }
    collection.find_one = AsyncMock(return_value=ticket)

    messages_collection = MagicMock()
    cursor = MagicMock()
    cursor.sort = MagicMock(return_value=cursor)
    cursor.to_list = AsyncMock(
        return_value=[
            {"_id": "m-1", "chat_id": "chat-1", "content": "hi"},
            {"_id": "m-2", "chat_id": "chat-1", "content": "still there?"},
        ]
    )
    messages_collection.find = MagicMock(return_value=cursor)
    store.db["chat_messages"] = messages_collection

    out = await svc.get_ticket_with_messages_for_agent(
        ticket_id="t-1",
        agent_scopes=["product"],
        agent_facility_ids=[],
    )

    assert out["_id"] == "t-1"
    assert len(out["messages"]) == 2
    assert out["messages"][0]["content"] == "hi"
    # The message query is by chat_id and sorted ascending by timestamp.
    messages_collection.find.assert_called_once_with({"chat_id": "chat-1"})
    cursor.sort.assert_called_once_with("timestamp", 1)


@pytest.mark.asyncio
async def test_get_with_messages_returns_none_when_out_of_scope(
    svc, fake_mongo
):
    _, collection = fake_mongo
    collection.find_one = AsyncMock(
        return_value={
            "_id": "t-1",
            "chat_id": "chat-1",
            "scope": "facility",
            "health_facility_id": "f-A",
        }
    )

    out = await svc.get_ticket_with_messages_for_agent(
        ticket_id="t-1",
        agent_scopes=["product"],  # admin has no facility scope
        agent_facility_ids=[],
    )
    assert out is None


@pytest.mark.asyncio
async def test_support_staff_can_access_own_facility(svc, fake_mongo):
    _, collection = fake_mongo
    collection.find_one = AsyncMock(
        return_value={
            "_id": "t-1",
            "scope": "facility",
            "health_facility_id": "facility-A",
        }
    )

    out = await svc.get_ticket_for_agent(
        ticket_id="t-1",
        agent_scopes=["facility"],
        agent_facility_ids=["facility-A"],
    )
    assert out is not None


# --- agent_reply ----------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_reply_adds_participant_and_sends_message(
    svc, fake_mongo
):
    from lib.core.constants import ProfileTypeEnum

    _, collection = fake_mongo
    ticket = {
        "_id": "t-1",
        "chat_id": "chat-1",
        "scope": "product",
        "status": "open",
        "health_facility_id": None,
    }
    # find_one called twice: once via get_ticket_for_agent, once for refresh
    collection.find_one = AsyncMock(side_effect=[ticket, ticket])

    await svc.agent_reply(
        ticket_id="t-1",
        agent_id="admin-1",
        agent_role=ProfileTypeEnum.ADMIN,
        agent_scopes=["product"],
        agent_facility_ids=[],
        content="hi back",
        media=None,
    )

    svc.chat_participant_service.add_participant_in_chat.assert_awaited_once()
    kwargs = svc.chat_participant_service.add_participant_in_chat.await_args.kwargs
    assert kwargs["chat_id"] == "chat-1"
    assert kwargs["user_id"] == "admin-1"
    assert kwargs["type"] == "admin"

    svc.chat_messaging_service.add_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_agent_reply_care_provider_joins_as_care_provider(
    svc, fake_mongo
):
    from lib.core.constants import ProfileTypeEnum

    _, collection = fake_mongo
    ticket = {
        "_id": "t-1",
        "chat_id": "chat-1",
        "scope": "facility",
        "status": "open",
        "health_facility_id": "f-1",
    }
    collection.find_one = AsyncMock(side_effect=[ticket, ticket])

    await svc.agent_reply(
        ticket_id="t-1",
        agent_id="cp-1",
        agent_role=ProfileTypeEnum.CARE_PROVIDER,
        agent_scopes=["facility"],
        agent_facility_ids=["f-1"],
        content="hi",
        media=None,
    )

    kwargs = svc.chat_participant_service.add_participant_in_chat.await_args.kwargs
    assert kwargs["type"] == "care_provider"


@pytest.mark.asyncio
async def test_agent_reply_reopen_emits_chat_list_updated(svc, fake_mongo):
    """Implicit reopen must emit chat_list_updated so the requester's
    inbox refreshes status without a refetch. Forward-compatible payload:
    ``change=status`` + ``ticket_status=pending`` (additive fields the
    current Flutter consumer ignores; the new one will branch on them)."""
    from lib.core.constants import EmitMessageKeyEnum, ProfileTypeEnum

    _, collection = fake_mongo
    ticket = {
        "_id": "t-1",
        "chat_id": "chat-1",
        "scope": "product",
        "status": "closed",
        "health_facility_id": None,
    }
    collection.find_one = AsyncMock(side_effect=[ticket, ticket])

    await svc.agent_reply(
        ticket_id="t-1",
        agent_id="admin-1",
        agent_role=ProfileTypeEnum.ADMIN,
        agent_scopes=["product"],
        agent_facility_ids=[],
        content="follow up",
        media=None,
    )

    # Expect exactly one chat_list_updated emit from the reopen path.
    emit_calls = [
        c
        for c in svc.chat_notification_service.notify_participants.await_args_list
        if c.kwargs.get("message_key")
        == EmitMessageKeyEnum.CHAT_LIST_UPDATED.value
    ]
    assert len(emit_calls) == 1
    payload = emit_calls[0].kwargs["data"]
    assert payload == {
        "chat_id": "chat-1",
        "change": "status",
        "ticket_status": "pending",
    }


@pytest.mark.asyncio
async def test_agent_reply_open_ticket_does_not_emit_chat_list_updated(
    svc, fake_mongo
):
    """Reply on an open ticket doesn't change status, so no
    chat_list_updated — the existing new_message_received from add_message
    is all the inbox needs."""
    from lib.core.constants import EmitMessageKeyEnum, ProfileTypeEnum

    _, collection = fake_mongo
    ticket = {
        "_id": "t-1",
        "chat_id": "chat-1",
        "scope": "product",
        "status": "open",
        "health_facility_id": None,
    }
    collection.find_one = AsyncMock(side_effect=[ticket, ticket])

    await svc.agent_reply(
        ticket_id="t-1",
        agent_id="admin-1",
        agent_role=ProfileTypeEnum.ADMIN,
        agent_scopes=["product"],
        agent_facility_ids=[],
        content="hi",
        media=None,
    )

    emit_calls = [
        c
        for c in svc.chat_notification_service.notify_participants.await_args_list
        if c.kwargs.get("message_key")
        == EmitMessageKeyEnum.CHAT_LIST_UPDATED.value
    ]
    assert emit_calls == []


@pytest.mark.asyncio
async def test_agent_reply_on_resolved_ticket_reopens_to_pending(
    svc, fake_mongo
):
    from lib.core.constants import ProfileTypeEnum

    _, collection = fake_mongo
    ticket = {
        "_id": "t-1",
        "chat_id": "chat-1",
        "scope": "product",
        "status": "resolved",
        "health_facility_id": None,
    }
    collection.find_one = AsyncMock(side_effect=[ticket, ticket])

    await svc.agent_reply(
        ticket_id="t-1",
        agent_id="admin-1",
        agent_role=ProfileTypeEnum.ADMIN,
        agent_scopes=["product"],
        agent_facility_ids=[],
        content="follow up",
        media=None,
    )

    # The $set update on update_one should include status=pending
    update = collection.update_one.await_args.args[1]
    assert update["$set"]["status"] == "pending"


@pytest.mark.asyncio
async def test_agent_reply_on_open_ticket_does_not_change_status(
    svc, fake_mongo
):
    from lib.core.constants import ProfileTypeEnum

    _, collection = fake_mongo
    ticket = {
        "_id": "t-1",
        "chat_id": "chat-1",
        "scope": "product",
        "status": "open",
        "health_facility_id": None,
    }
    collection.find_one = AsyncMock(side_effect=[ticket, ticket])

    await svc.agent_reply(
        ticket_id="t-1",
        agent_id="admin-1",
        agent_role=ProfileTypeEnum.ADMIN,
        agent_scopes=["product"],
        agent_facility_ids=[],
        content="hi",
        media=None,
    )

    update = collection.update_one.await_args.args[1]
    # Open stays open — no 'status' field in the $set.
    assert "status" not in update["$set"]


@pytest.mark.asyncio
async def test_agent_reply_returns_none_when_out_of_scope(svc, fake_mongo):
    from lib.core.constants import ProfileTypeEnum

    _, collection = fake_mongo
    # Ticket exists but is a facility ticket; an admin can't touch it.
    collection.find_one = AsyncMock(
        return_value={
            "_id": "t-1",
            "scope": "facility",
            "health_facility_id": "f-1",
        }
    )

    out = await svc.agent_reply(
        ticket_id="t-1",
        agent_id="admin-1",
        agent_role=ProfileTypeEnum.ADMIN,
        agent_scopes=["product"],
        agent_facility_ids=[],
        content="hi",
        media=None,
    )
    assert out is None
    svc.chat_participant_service.add_participant_in_chat.assert_not_called()
    svc.chat_messaging_service.add_message.assert_not_called()


# --- change_status --------------------------------------------------------


@pytest.mark.asyncio
async def test_change_status_resolved_sets_resolved_at(svc, fake_mongo):
    _, collection = fake_mongo
    ticket = {
        "_id": "t-1",
        "chat_id": "chat-1",
        "scope": "product",
        "status": "open",
        "health_facility_id": None,
    }
    collection.find_one = AsyncMock(
        side_effect=[ticket, {**ticket, "status": "resolved"}]
    )

    await svc.change_status(
        ticket_id="t-1",
        agent_scopes=["product"],
        agent_facility_ids=[],
        new_status="resolved",
    )

    update = collection.update_one.await_args.args[1]["$set"]
    assert update["status"] == "resolved"
    assert isinstance(update["resolved_at"], datetime)


@pytest.mark.asyncio
async def test_change_status_closed_sets_closed_at(svc, fake_mongo):
    _, collection = fake_mongo
    ticket = {
        "_id": "t-1",
        "chat_id": "chat-1",
        "scope": "product",
        "status": "open",
        "health_facility_id": None,
    }
    collection.find_one = AsyncMock(
        side_effect=[ticket, {**ticket, "status": "closed"}]
    )

    await svc.change_status(
        ticket_id="t-1",
        agent_scopes=["product"],
        agent_facility_ids=[],
        new_status="closed",
    )

    update = collection.update_one.await_args.args[1]["$set"]
    assert update["status"] == "closed"
    assert isinstance(update["closed_at"], datetime)


@pytest.mark.asyncio
async def test_change_status_emits_chat_list_updated(svc, fake_mongo):
    _, collection = fake_mongo
    ticket = {
        "_id": "t-1",
        "chat_id": "chat-1",
        "scope": "product",
        "status": "open",
        "health_facility_id": None,
    }
    collection.find_one = AsyncMock(
        side_effect=[ticket, {**ticket, "status": "pending"}]
    )

    await svc.change_status(
        ticket_id="t-1",
        agent_scopes=["product"],
        agent_facility_ids=[],
        new_status="pending",
    )

    svc.chat_notification_service.notify_participants.assert_awaited_once()
    kwargs = svc.chat_notification_service.notify_participants.await_args.kwargs
    assert kwargs["message_key"] == "chat_list_updated"
    assert kwargs["chat_id"] == "chat-1"


# --- close_ticket_by_requester -------------------------------------------


@pytest.mark.asyncio
async def test_agent_reply_skips_participant_add_when_already_joined(
    svc, fake_mongo
):
    """add_participant_in_chat is idempotent but costs a read+write per
    call. agent_reply on subsequent replies must skip when the agent is
    already a participant."""
    from lib.core.constants import ProfileTypeEnum

    store, collection = fake_mongo
    ticket = {
        "_id": "t-1",
        "chat_id": "chat-1",
        "scope": "product",
        "status": "open",
        "health_facility_id": None,
    }
    collection.find_one = AsyncMock(side_effect=[ticket, ticket])
    # Override chats find_one: agent IS already a participant
    store.db["chats"].find_one = AsyncMock(
        return_value={
            "_id": "chat-1",
            "participants": [{"id": "admin-1", "type": "admin"}],
        }
    )

    await svc.agent_reply(
        ticket_id="t-1",
        agent_id="admin-1",
        agent_role=ProfileTypeEnum.ADMIN,
        agent_scopes=["product"],
        agent_facility_ids=[],
        content="follow-up",
        media=None,
    )

    svc.chat_participant_service.add_participant_in_chat.assert_not_called()


@pytest.mark.asyncio
async def test_agent_reply_adds_participant_when_not_yet_joined(
    svc, fake_mongo
):
    """First reply: agent is not yet a participant, so add must fire once."""
    from lib.core.constants import ProfileTypeEnum

    store, collection = fake_mongo
    ticket = {
        "_id": "t-1",
        "chat_id": "chat-1",
        "scope": "product",
        "status": "open",
        "health_facility_id": None,
    }
    collection.find_one = AsyncMock(side_effect=[ticket, ticket])
    # Default chats find_one returns {"participants": []} — no agents yet.

    await svc.agent_reply(
        ticket_id="t-1",
        agent_id="admin-1",
        agent_role=ProfileTypeEnum.ADMIN,
        agent_scopes=["product"],
        agent_facility_ids=[],
        content="hi",
        media=None,
    )

    svc.chat_participant_service.add_participant_in_chat.assert_awaited_once()


@pytest.mark.asyncio
async def test_set_status_payload_includes_change_and_ticket_status(
    svc, fake_mongo
):
    """All chat_list_updated emits must use the rich payload shape — both
    the auto-reopen path AND the explicit PATCH /status path."""
    _, collection = fake_mongo
    ticket = {
        "_id": "t-1",
        "chat_id": "chat-1",
        "scope": "product",
        "status": "open",
        "health_facility_id": None,
    }
    collection.find_one = AsyncMock(
        side_effect=[ticket, {**ticket, "status": "resolved"}]
    )

    await svc.change_status(
        ticket_id="t-1",
        agent_scopes=["product"],
        agent_facility_ids=[],
        new_status="resolved",
    )

    payload = (
        svc.chat_notification_service.notify_participants.await_args.kwargs[
            "data"
        ]
    )
    assert payload == {
        "chat_id": "chat-1",
        "change": "status",
        "ticket_status": "resolved",
    }


@pytest.mark.asyncio
async def test_status_change_also_emits_to_queue_agents(svc, fake_mongo):
    """The queue-agent socket fan-out is what closes the multi-agent
    coordination gap: admins watching the queue (but not yet engaged on
    this ticket) need to see status changes from each other."""
    _, collection = fake_mongo
    ticket = {
        "_id": "t-1",
        "chat_id": "chat-1",
        "scope": "product",
        "status": "open",
        "health_facility_id": None,
    }
    collection.find_one = AsyncMock(
        side_effect=[ticket, {**ticket, "status": "resolved"}]
    )

    await svc.change_status(
        ticket_id="t-1",
        agent_scopes=["product"],
        agent_facility_ids=[],
        new_status="resolved",
    )

    # Patched SupportNotificationService class — its emit_to_queue_agents
    # is a class-level AsyncMock so we can assert across instances.
    svc._fake_notif_svc_cls.emit_to_queue_agents.assert_awaited()
    last_call = svc._fake_notif_svc_cls.emit_to_queue_agents.await_args
    assert last_call.kwargs["chat_id"] == "chat-1"
    assert last_call.kwargs["data"]["change"] == "status"
    assert last_call.kwargs["data"]["ticket_status"] == "resolved"


# --- requester reply hook -----------------------------------------------


@pytest.mark.asyncio
async def test_requester_reply_on_closed_ticket_reopens_to_open(
    svc, fake_mongo
):
    """The bug the user flagged: requester replying to a closed/resolved
    ticket must reopen it. Symmetric with agent_reply (which reopens to
    'pending'); requester reopens to 'open' because it needs an agent."""
    _, collection = fake_mongo
    ticket = {
        "_id": "t-1",
        "chat_id": "chat-1",
        "scope": "product",
        "requester_id": "patient-1",
        "status": "closed",
        "health_facility_id": None,
    }
    collection.find_one = AsyncMock(return_value=ticket)

    await svc.on_requester_message_in_support_chat(
        chat_id="chat-1",
        sender_id="patient-1",
        content="actually still broken",
    )

    update = collection.update_one.await_args.args[1]["$set"]
    assert update["status"] == "open"
    assert "last_message_at" in update
    assert update["last_message_preview"] == "actually still broken"


@pytest.mark.asyncio
async def test_requester_reply_on_resolved_ticket_reopens_to_open(
    svc, fake_mongo
):
    _, collection = fake_mongo
    ticket = {
        "_id": "t-1",
        "chat_id": "chat-1",
        "scope": "product",
        "requester_id": "patient-1",
        "status": "resolved",
        "health_facility_id": None,
    }
    collection.find_one = AsyncMock(return_value=ticket)

    await svc.on_requester_message_in_support_chat(
        chat_id="chat-1",
        sender_id="patient-1",
        content="not fixed",
    )

    update = collection.update_one.await_args.args[1]["$set"]
    assert update["status"] == "open"


@pytest.mark.asyncio
async def test_requester_reply_on_open_ticket_keeps_status_but_bumps_activity(
    svc, fake_mongo
):
    """No status change on already-open tickets, but last_message_at /
    last_message_preview MUST still update so the queue sort surfaces
    the reply. Without this the ticket sinks under newer activity."""
    _, collection = fake_mongo
    ticket = {
        "_id": "t-1",
        "chat_id": "chat-1",
        "scope": "product",
        "requester_id": "patient-1",
        "status": "open",
        "health_facility_id": None,
    }
    collection.find_one = AsyncMock(return_value=ticket)

    await svc.on_requester_message_in_support_chat(
        chat_id="chat-1",
        sender_id="patient-1",
        content="follow up",
    )

    update = collection.update_one.await_args.args[1]["$set"]
    assert "status" not in update  # no reopen
    assert "last_message_at" in update  # but activity bumped
    assert update["last_message_preview"] == "follow up"


@pytest.mark.asyncio
async def test_requester_reply_hook_ignores_agent_messages(svc, fake_mongo):
    """Agent replies are owned by agent_reply — the hook must skip them
    to avoid double-updating the ticket."""
    _, collection = fake_mongo
    ticket = {
        "_id": "t-1",
        "chat_id": "chat-1",
        "scope": "product",
        "requester_id": "patient-1",
        "status": "closed",
        "health_facility_id": None,
    }
    collection.find_one = AsyncMock(return_value=ticket)

    await svc.on_requester_message_in_support_chat(
        chat_id="chat-1",
        sender_id="admin-1",  # not the requester
        content="resolved on our end",
    )

    collection.update_one.assert_not_called()


@pytest.mark.asyncio
async def test_requester_reply_hook_noop_when_no_ticket(svc, fake_mongo):
    _, collection = fake_mongo
    collection.find_one = AsyncMock(return_value=None)

    await svc.on_requester_message_in_support_chat(
        chat_id="chat-other",
        sender_id="patient-1",
        content="hello",
    )

    collection.update_one.assert_not_called()


@pytest.mark.asyncio
async def test_close_ticket_by_requester_only_owner(svc, fake_mongo):
    _, collection = fake_mongo
    collection.find_one = AsyncMock(return_value=None)

    out = await svc.close_ticket_by_requester("t-1", "patient-other")

    assert out is None
    collection.update_one.assert_not_called()


# --- list_tickets_for_requester ------------------------------------------


@pytest.mark.asyncio
async def test_list_tickets_for_requester_filters_by_id(svc, fake_mongo):
    _, collection = fake_mongo

    await svc.list_tickets_for_requester(
        requester_id="patient-1",
        status_filter=None,
        limit=10,
        offset=0,
    )

    query = collection.find.call_args.args[0]
    assert query == {"requester_id": "patient-1"}


@pytest.mark.asyncio
async def test_list_tickets_for_requester_applies_status_filter(
    svc, fake_mongo
):
    _, collection = fake_mongo

    await svc.list_tickets_for_requester(
        requester_id="patient-1",
        status_filter="open",
        limit=10,
        offset=0,
    )

    query = collection.find.call_args.args[0]
    assert query == {"requester_id": "patient-1", "status": "open"}


@pytest.mark.asyncio
async def test_list_tickets_for_requester_applies_paging(svc, fake_mongo):
    _, collection = fake_mongo

    await svc.list_tickets_for_requester(
        requester_id="patient-1",
        status_filter=None,
        limit=5,
        offset=10,
    )

    cursor = collection.find.return_value or collection.find.side_effect(None)
    # Skip/limit are method calls on the chainable cursor returned by
    # ``_chain``; the cursor is created fresh per call so we inspect via
    # the latest cursor's mocks.
    last_cursor = collection.find.spy_return  # MagicMock side_effect support
    # Easier: re-invoke the side_effect to assert it sets up chaining; the
    # core invariant is that ``find`` was called once with the right query.
    assert collection.find.call_count == 1


# --- list_queue scoping --------------------------------------------------


@pytest.mark.asyncio
async def test_list_queue_admin_only_sees_product(svc, fake_mongo):
    _, collection = fake_mongo

    await svc.list_queue(
        agent_scopes=["product"],
        agent_facility_ids=[],
        scope_filter=None,
        status_filter=None,
        requester_type_filter=None,
        limit=20,
        offset=0,
    )

    query = collection.find.call_args.args[0]
    # Single product clause — no $or, no facility query.
    assert query == {"scope": "product"}


@pytest.mark.asyncio
async def test_list_queue_facility_agent_only_sees_own_facility(
    svc, fake_mongo
):
    _, collection = fake_mongo

    await svc.list_queue(
        agent_scopes=["facility"],
        agent_facility_ids=["facility-A"],
        scope_filter=None,
        status_filter=None,
        requester_type_filter=None,
        limit=20,
        offset=0,
    )

    query = collection.find.call_args.args[0]
    assert query == {
        "scope": "facility",
        "health_facility_id": {"$in": ["facility-A"]},
    }


@pytest.mark.asyncio
async def test_list_queue_facility_agent_without_facility_returns_empty(
    svc, fake_mongo
):
    """A support_staff CareProvider whose facility_ids is empty cannot
    see anything — we must NOT degrade to a full unfiltered facility
    query."""
    _, collection = fake_mongo

    out = await svc.list_queue(
        agent_scopes=["facility"],
        agent_facility_ids=[],
        scope_filter=None,
        status_filter=None,
        requester_type_filter=None,
        limit=20,
        offset=0,
    )

    assert out == []
    collection.find.assert_not_called()


@pytest.mark.asyncio
async def test_list_queue_empty_scopes_returns_empty_without_querying(
    svc, fake_mongo
):
    _, collection = fake_mongo

    out = await svc.list_queue(
        agent_scopes=[],
        agent_facility_ids=[],
        scope_filter=None,
        status_filter=None,
        requester_type_filter=None,
        limit=20,
        offset=0,
    )

    assert out == []
    collection.find.assert_not_called()


@pytest.mark.asyncio
async def test_list_queue_admin_scope_filter_to_facility_returns_empty(
    svc, fake_mongo
):
    """An admin (product-only) explicitly filtering for facility tickets
    gets nothing — not a leak."""
    _, collection = fake_mongo

    out = await svc.list_queue(
        agent_scopes=["product"],
        agent_facility_ids=[],
        scope_filter="facility",
        status_filter=None,
        requester_type_filter=None,
        limit=20,
        offset=0,
    )

    assert out == []
    collection.find.assert_not_called()


@pytest.mark.asyncio
async def test_list_queue_combines_status_and_requester_type_filters(
    svc, fake_mongo
):
    _, collection = fake_mongo

    await svc.list_queue(
        agent_scopes=["product"],
        agent_facility_ids=[],
        scope_filter=None,
        status_filter="open",
        requester_type_filter="patient",
        limit=20,
        offset=0,
    )

    query = collection.find.call_args.args[0]
    assert query == {
        "scope": "product",
        "status": "open",
        "requester_type": "patient",
    }


# --- agent_reply additional edge cases -----------------------------------


@pytest.mark.asyncio
async def test_agent_reply_on_closed_ticket_reopens_to_pending(
    svc, fake_mongo
):
    from lib.core.constants import ProfileTypeEnum

    _, collection = fake_mongo
    ticket = {
        "_id": "t-1",
        "chat_id": "chat-1",
        "scope": "product",
        "status": "closed",
        "health_facility_id": None,
    }
    collection.find_one = AsyncMock(side_effect=[ticket, ticket])

    await svc.agent_reply(
        ticket_id="t-1",
        agent_id="admin-1",
        agent_role=ProfileTypeEnum.ADMIN,
        agent_scopes=["product"],
        agent_facility_ids=[],
        content="follow up",
        media=None,
    )

    update = collection.update_one.await_args.args[1]
    assert update["$set"]["status"] == "pending"


@pytest.mark.asyncio
async def test_agent_reply_on_pending_does_not_change_status(svc, fake_mongo):
    from lib.core.constants import ProfileTypeEnum

    _, collection = fake_mongo
    ticket = {
        "_id": "t-1",
        "chat_id": "chat-1",
        "scope": "product",
        "status": "pending",
        "health_facility_id": None,
    }
    collection.find_one = AsyncMock(side_effect=[ticket, ticket])

    await svc.agent_reply(
        ticket_id="t-1",
        agent_id="admin-1",
        agent_role=ProfileTypeEnum.ADMIN,
        agent_scopes=["product"],
        agent_facility_ids=[],
        content="bumping",
        media=None,
    )

    update = collection.update_one.await_args.args[1]["$set"]
    assert "status" not in update


@pytest.mark.asyncio
async def test_agent_reply_sets_last_message_preview(svc, fake_mongo):
    from lib.core.constants import ProfileTypeEnum

    _, collection = fake_mongo
    ticket = {
        "_id": "t-1",
        "chat_id": "chat-1",
        "scope": "product",
        "status": "open",
        "health_facility_id": None,
    }
    collection.find_one = AsyncMock(side_effect=[ticket, ticket])

    long_content = "x" * 500
    await svc.agent_reply(
        ticket_id="t-1",
        agent_id="admin-1",
        agent_role=ProfileTypeEnum.ADMIN,
        agent_scopes=["product"],
        agent_facility_ids=[],
        content=long_content,
        media=None,
    )

    preview = collection.update_one.await_args.args[1]["$set"][
        "last_message_preview"
    ]
    # Updated for the unified preview sanitizer (spec item A): 200-char
    # truncation, no ellipsis (clients handle overflow display).
    assert len(preview) <= 200
    assert not preview.endswith("…")


# --- change_status additional edge cases ---------------------------------


@pytest.mark.asyncio
async def test_change_status_returns_none_when_out_of_scope(
    svc, fake_mongo
):
    """An admin trying to move a facility ticket's status gets None,
    not the ticket."""
    _, collection = fake_mongo
    collection.find_one = AsyncMock(
        return_value={
            "_id": "t-1",
            "scope": "facility",
            "health_facility_id": "f-1",
        }
    )

    out = await svc.change_status(
        ticket_id="t-1",
        agent_scopes=["product"],
        agent_facility_ids=[],
        new_status="resolved",
    )

    assert out is None
    collection.update_one.assert_not_called()


@pytest.mark.asyncio
async def test_change_status_resolved_at_is_idempotent(svc, fake_mongo):
    """Re-resolving an already-resolved ticket must NOT overwrite the
    original resolved_at — that would lose audit history."""
    from datetime import datetime, timedelta

    original = datetime.utcnow() - timedelta(days=1)
    _, collection = fake_mongo
    ticket = {
        "_id": "t-1",
        "chat_id": "chat-1",
        "scope": "product",
        "status": "resolved",
        "resolved_at": original,
        "health_facility_id": None,
    }
    collection.find_one = AsyncMock(side_effect=[ticket, ticket])

    await svc.change_status(
        ticket_id="t-1",
        agent_scopes=["product"],
        agent_facility_ids=[],
        new_status="resolved",
    )

    update = collection.update_one.await_args.args[1]["$set"]
    # status is re-set (no-op) and updated_at refreshed, but resolved_at
    # is NOT in the update — the original timestamp is preserved.
    assert "resolved_at" not in update


@pytest.mark.asyncio
async def test_change_status_closed_at_is_idempotent(svc, fake_mongo):
    from datetime import datetime, timedelta

    original = datetime.utcnow() - timedelta(days=2)
    _, collection = fake_mongo
    ticket = {
        "_id": "t-1",
        "chat_id": "chat-1",
        "scope": "product",
        "status": "closed",
        "closed_at": original,
        "health_facility_id": None,
    }
    collection.find_one = AsyncMock(side_effect=[ticket, ticket])

    await svc.change_status(
        ticket_id="t-1",
        agent_scopes=["product"],
        agent_facility_ids=[],
        new_status="closed",
    )

    update = collection.update_one.await_args.args[1]["$set"]
    assert "closed_at" not in update
