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
    ``find().sort().skip().limit().to_list()``."""
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

    store = MagicMock()
    store.db = {"support_tickets": collection}
    store.insert_document = AsyncMock()
    return store, collection


@pytest.fixture
def fake_mongo():
    return _make_fake_mongo()


@pytest.fixture
def svc(fake_mongo):
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
async def test_close_ticket_by_requester_only_owner(svc, fake_mongo):
    _, collection = fake_mongo
    collection.find_one = AsyncMock(return_value=None)

    out = await svc.close_ticket_by_requester("t-1", "patient-other")

    assert out is None
    collection.update_one.assert_not_called()
