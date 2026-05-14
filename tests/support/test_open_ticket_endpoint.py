"""POST /v1/support_tickets — endpoint-level behavior (spec item G).

The response carries the full chat record under a ``chat`` key so the
client can navigate to the thread without a follow-up fetch. Same shape
as one element of GET /chats (participants enriched with PG profile
data).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

import lib.models  # noqa: F401,E402
from lib.models.patient import Patient  # noqa: F401,E402

from lib.core.constants import ProfileTypeEnum  # noqa: E402
from lib.schemas.support_ticket import SupportTicketOpenRequest  # noqa: E402
from rest_server.v1.support_tickets.create import (  # noqa: E402
    open_support_ticket,
)


def _make_actor(role=ProfileTypeEnum.PATIENT, facility_id=None):
    return SimpleNamespace(
        id=str(uuid4()),
        role=role,
        model=SimpleNamespace(health_facility_id=facility_id),
    )


def _make_ticket(chat_id="chat-1"):
    return {
        "_id": "ticket-1",
        "chat_id": chat_id,
        "scope": "product",
        "status": "open",
        "requester_id": "patient-1",
        "requester_type": "patient",
    }


def _make_enriched_chat(chat_id="chat-1"):
    return {
        "_id": chat_id,
        "kind": "support",
        "sender": {"id": "patient-1", "type": "patient"},
        "receivers": [],
        "unread_counts": {"patient-1": 0},
        "last_message": {"_id": "m-1", "content": "hello"},
    }


@pytest.mark.asyncio
async def test_response_includes_full_chat_record():
    """Client navigates to the new thread using only this response —
    chat must be inline, fully enriched, no follow-up fetch required."""
    actor = _make_actor()
    body = SupportTicketOpenRequest(scope="product", initial_message="hi")

    support_svc = MagicMock()
    support_svc.open_ticket = AsyncMock(return_value=_make_ticket())
    chat_svc = MagicMock()
    chat_svc.fetch_single_chat = AsyncMock(
        return_value=_make_enriched_chat()
    )
    patient_svc = MagicMock()
    patient_svc.fetch_patient_profiles = AsyncMock(return_value={})
    cp_svc = MagicMock()
    cp_svc.fetch_care_provider_profiles = AsyncMock(return_value={})

    response = await open_support_ticket(
        body=body,
        actor=actor,
        support_ticket_service=support_svc,
        chat_management_service=chat_svc,
        patient_profile_service=patient_svc,
        care_provider_profile_service=cp_svc,
    )

    assert response.data["_id"] == "ticket-1"
    assert response.data["chat_id"] == "chat-1"
    assert "chat" in response.data
    assert response.data["chat"]["_id"] == "chat-1"
    assert response.data["chat"]["kind"] == "support"


@pytest.mark.asyncio
async def test_chat_fetch_uses_authenticated_user_for_access_check():
    """fetch_single_chat is participant-gated. Must pass actor.id so the
    pipeline access check succeeds — passing any other id would return
    None and silently drop the chat from the response."""
    actor = _make_actor()
    body = SupportTicketOpenRequest(scope="product", initial_message="hi")

    support_svc = MagicMock()
    support_svc.open_ticket = AsyncMock(return_value=_make_ticket())
    chat_svc = MagicMock()
    chat_svc.fetch_single_chat = AsyncMock(
        return_value=_make_enriched_chat()
    )

    await open_support_ticket(
        body=body,
        actor=actor,
        support_ticket_service=support_svc,
        chat_management_service=chat_svc,
        patient_profile_service=MagicMock(
            fetch_patient_profiles=AsyncMock(return_value={})
        ),
        care_provider_profile_service=MagicMock(
            fetch_care_provider_profiles=AsyncMock(return_value={})
        ),
    )

    chat_svc.fetch_single_chat.assert_awaited_once_with(
        "chat-1", actor.id
    )


@pytest.mark.asyncio
async def test_missing_chat_does_not_break_response():
    """Defensive: if fetch_single_chat returns None (shouldn't happen in
    practice — we just created the chat — but races exist), the ticket
    still comes back without a chat key. Client falls back to its
    existing path (fetch /chats)."""
    actor = _make_actor()
    body = SupportTicketOpenRequest(scope="product", initial_message="hi")

    support_svc = MagicMock()
    support_svc.open_ticket = AsyncMock(return_value=_make_ticket())
    chat_svc = MagicMock()
    chat_svc.fetch_single_chat = AsyncMock(return_value=None)

    response = await open_support_ticket(
        body=body,
        actor=actor,
        support_ticket_service=support_svc,
        chat_management_service=chat_svc,
        patient_profile_service=MagicMock(
            fetch_patient_profiles=AsyncMock(return_value={})
        ),
        care_provider_profile_service=MagicMock(
            fetch_care_provider_profiles=AsyncMock(return_value={})
        ),
    )

    assert response.data["_id"] == "ticket-1"
    assert "chat" not in response.data


@pytest.mark.asyncio
async def test_actor_facility_overrides_body_facility_id():
    """Independent of G but worth re-asserting at the endpoint level —
    the body's health_facility_id is ignored; the actor's wins. This is
    the privacy-bug fix from the audit, regression-protected here."""
    actor = _make_actor(
        role=ProfileTypeEnum.CARE_PROVIDER,
        facility_id="trusted-facility-id",
    )
    # Schema validator forces body.health_facility_id non-empty when
    # scope=facility — supply a deliberately wrong value to ensure the
    # endpoint drops it.
    body = SupportTicketOpenRequest(
        scope="facility",
        initial_message="hi",
        health_facility_id="attacker-supplied-id",
    )

    support_svc = MagicMock()
    support_svc.open_ticket = AsyncMock(
        return_value=_make_ticket(chat_id="chat-1")
    )
    chat_svc = MagicMock()
    chat_svc.fetch_single_chat = AsyncMock(return_value=None)

    await open_support_ticket(
        body=body,
        actor=actor,
        support_ticket_service=support_svc,
        chat_management_service=chat_svc,
        patient_profile_service=MagicMock(
            fetch_patient_profiles=AsyncMock(return_value={})
        ),
        care_provider_profile_service=MagicMock(
            fetch_care_provider_profiles=AsyncMock(return_value={})
        ),
    )

    call_kwargs = support_svc.open_ticket.await_args.kwargs
    assert call_kwargs["health_facility_id"] == "trusted-facility-id"
    assert call_kwargs["health_facility_id"] != "attacker-supplied-id"
