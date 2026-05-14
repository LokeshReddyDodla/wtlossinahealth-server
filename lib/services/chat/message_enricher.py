"""Attach ``sender_profile`` to message dicts AND ``profile`` to chat
participants.

Used by every code path that returns chat data to clients:
- GET /chats/messages
- GET /v1/admin/support_tickets/{id} (returns the thread)
- ChatMessagingService.add_message socket broadcast (so the inbox + thread
  views render the sender immediately, no race with chat-roster updates)
- GET /chats (existing list endpoint — participant profiles)
- GET /v1/chats/{chat_id} (single-chat fetch — same shape)
"""

from typing import Iterable

from fastapi.encoders import jsonable_encoder

from lib.core.constants import ProfileTypeEnum
from lib.schemas.care_provider import CareProvider as CareProviderSchema
from lib.schemas.patient_connected_app import PatientSchema
from lib.services.care_provider_profile_service import (
    CareProviderProfileService,
)
from lib.services.chat.profile_resolver_service import ProfileResolverService
from lib.services.patient_profile_service import PatientProfileService


async def enrich_messages_with_sender_profiles(
    messages: Iterable[dict],
) -> list[dict]:
    """Return new dicts with a ``sender_profile`` field attached to each.

    Batches all sender_ids into a single resolver call so a thread with
    50 messages from 3 senders runs 3 PG queries (one per role table),
    not 150. Idempotent — if a message already has a sender_profile it
    gets overwritten with the freshly-resolved one.
    """
    materialized = [dict(m) for m in messages]
    if not materialized:
        return materialized

    sender_ids = {m["sender_id"] for m in materialized if m.get("sender_id")}
    if not sender_ids:
        return materialized

    profiles = await ProfileResolverService().resolve(sender_ids)
    for m in materialized:
        sid = m.get("sender_id")
        profile = profiles.get(str(sid)) if sid else None
        if profile is not None:
            m["sender_profile"] = jsonable_encoder(profile)
    return materialized


async def enrich_single_message_with_sender_profile(
    message: dict,
) -> dict:
    """Convenience wrapper for single-message paths (the socket broadcast)."""
    enriched = await enrich_messages_with_sender_profiles([message])
    return enriched[0] if enriched else message


async def attach_participant_profiles(
    chats: list[dict],
    patient_profile_service: PatientProfileService,
    care_provider_profile_service: CareProviderProfileService,
) -> None:
    """Mutate ``chats`` in place, attaching ``profile`` to each
    participant (sender + receivers).

    Extracts what was inline in ``rest_server/chats/read.py:get_user_chats``
    so both the chat-list endpoint and the new single-chat endpoint emit
    exactly the same shape. Two PG queries total (one per role) regardless
    of how many chats are in the input.
    """
    if not chats:
        return

    patient_ids = {
        p["id"]
        for chat in chats
        for p in chat.get("participants", [])
        if p.get("type") == ProfileTypeEnum.PATIENT.value
    }
    care_provider_ids = {
        p["id"]
        for chat in chats
        for p in chat.get("participants", [])
        if p.get("type") == ProfileTypeEnum.CARE_PROVIDER.value
    }

    patient_profiles = (
        await patient_profile_service.fetch_patient_profiles(
            list(patient_ids)
        )
        if patient_ids
        else {}
    )
    care_provider_profiles = (
        await care_provider_profile_service.fetch_care_provider_profiles(
            list(care_provider_ids)
        )
        if care_provider_ids
        else {}
    )

    def _attach_to(slot: dict) -> None:
        if not slot:
            return
        if slot.get("type") == ProfileTypeEnum.PATIENT.value:
            row = patient_profiles.get(slot["id"])
            if row:
                slot["profile"] = PatientSchema.from_orm(row)
        else:
            row = care_provider_profiles.get(slot["id"])
            if row:
                slot["profile"] = CareProviderSchema.from_orm(row)

    for chat in chats:
        _attach_to(chat.get("sender"))
        for receiver in chat.get("receivers", []) or []:
            _attach_to(receiver)
