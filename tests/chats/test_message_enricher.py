"""message_enricher — single source of truth for attaching profiles to
messages and chats.

Test isolation: ProfileResolverService is patched with a fake so we don't
hit PG; we're testing the enrichment seam, not the resolver.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

import lib.models  # noqa: F401,E402
from lib.models.patient import Patient  # noqa: F401,E402

from lib.schemas.sender_profile import SenderProfileSchema  # noqa: E402
from lib.services.chat import message_enricher as mod  # noqa: E402


def _profile(role="patient", first="Test", last="User"):
    return SenderProfileSchema(
        first_name=first, last_name=last, role=role
    )


@pytest.fixture
def fake_resolver(monkeypatch):
    """Replace ProfileResolverService class so callers get a stub whose
    .resolve() returns whatever we set _stub_return to."""
    stub = MagicMock()
    stub.resolve = AsyncMock(return_value={})

    class FakeCls:
        def __init__(self):
            pass

        async def resolve(self, ids):
            return await stub.resolve(ids)

    monkeypatch.setattr(mod, "ProfileResolverService", FakeCls)
    return stub


# --- enrich_messages_with_sender_profiles -------------------------------


@pytest.mark.asyncio
async def test_attaches_profile_to_each_message(fake_resolver):
    fake_resolver.resolve.return_value = {
        "u-1": _profile(first="Alice"),
        "u-2": _profile(role="support_staff", first="Priya"),
    }
    messages = [
        {"_id": "m-1", "sender_id": "u-1", "content": "hi"},
        {"_id": "m-2", "sender_id": "u-2", "content": "yo"},
    ]

    out = await mod.enrich_messages_with_sender_profiles(messages)

    assert out[0]["sender_profile"]["first_name"] == "Alice"
    assert out[0]["sender_profile"]["role"] == "patient"
    assert out[1]["sender_profile"]["first_name"] == "Priya"
    assert out[1]["sender_profile"]["role"] == "support_staff"


@pytest.mark.asyncio
async def test_resolver_called_with_unique_sender_ids_only(fake_resolver):
    """Long threads with repeated senders shouldn't blow up the resolver
    call. Dedup happens here too."""
    fake_resolver.resolve.return_value = {}
    messages = [
        {"sender_id": "u-1"},
        {"sender_id": "u-1"},
        {"sender_id": "u-2"},
        {"sender_id": "u-1"},
    ]

    await mod.enrich_messages_with_sender_profiles(messages)

    called_with = fake_resolver.resolve.await_args.args[0]
    assert set(called_with) == {"u-1", "u-2"}


@pytest.mark.asyncio
async def test_empty_input_returns_empty_list_no_resolver_call(
    fake_resolver,
):
    out = await mod.enrich_messages_with_sender_profiles([])
    assert out == []
    fake_resolver.resolve.assert_not_called()


@pytest.mark.asyncio
async def test_does_not_mutate_input(fake_resolver):
    """Critical for caller safety: the helper returns fresh dicts so
    upstream code that holds a reference to the original messages list
    doesn't suddenly grow sender_profile keys."""
    fake_resolver.resolve.return_value = {"u-1": _profile()}
    original = {"_id": "m-1", "sender_id": "u-1"}

    out = await mod.enrich_messages_with_sender_profiles([original])

    assert "sender_profile" not in original
    assert "sender_profile" in out[0]


# --- attach_participant_profiles ---------------------------------------


@pytest.mark.asyncio
async def test_attach_participant_profiles_skips_empty_input():
    """No chats → no PG calls. Defensive."""
    patient_svc = MagicMock()
    patient_svc.fetch_patient_profiles = AsyncMock(return_value={})
    cp_svc = MagicMock()
    cp_svc.fetch_care_provider_profiles = AsyncMock(return_value={})

    await mod.attach_participant_profiles(
        [],
        patient_profile_service=patient_svc,
        care_provider_profile_service=cp_svc,
    )

    patient_svc.fetch_patient_profiles.assert_not_called()
    cp_svc.fetch_care_provider_profiles.assert_not_called()


@pytest.mark.asyncio
async def test_attach_participant_profiles_synthesizes_unknown_patient():
    """Spec item E — participant.profile is GUARANTEED non-null. When
    the patient row can't be resolved (deleted account, stale chat doc,
    race), insert a synthesized 'Unknown User' placeholder so clients
    never need a fallback path."""
    patient_svc = MagicMock()
    patient_svc.fetch_patient_profiles = AsyncMock(return_value={})
    cp_svc = MagicMock()
    cp_svc.fetch_care_provider_profiles = AsyncMock(return_value={})

    chat = {
        "_id": "c-1",
        "participants": [
            {"id": "ghost-patient", "type": "patient"},
        ],
        "sender": {"id": "ghost-patient", "type": "patient"},
        "receivers": [],
    }
    await mod.attach_participant_profiles(
        [chat],
        patient_profile_service=patient_svc,
        care_provider_profile_service=cp_svc,
    )

    assert chat["sender"]["profile"] == {
        "first_name": "Unknown",
        "last_name": "User",
        "profile_picture": None,
    }


@pytest.mark.asyncio
async def test_attach_participant_profiles_synthesizes_unknown_care_provider():
    patient_svc = MagicMock()
    patient_svc.fetch_patient_profiles = AsyncMock(return_value={})
    cp_svc = MagicMock()
    cp_svc.fetch_care_provider_profiles = AsyncMock(return_value={})

    chat = {
        "_id": "c-1",
        "participants": [
            {"id": "ghost-cp", "type": "care_provider"},
        ],
        "sender": None,
        "receivers": [{"id": "ghost-cp", "type": "care_provider"}],
    }
    await mod.attach_participant_profiles(
        [chat],
        patient_profile_service=patient_svc,
        care_provider_profile_service=cp_svc,
    )

    assert chat["receivers"][0]["profile"] == {
        "first_name": "Unknown",
        "last_name": "User",
        "profile_picture": None,
    }


@pytest.mark.asyncio
async def test_attach_participant_profiles_admin_gets_support_team():
    """Admin participants get a 'Support Team' placeholder — we don't
    fetch Admin rows in this helper because the chat layer doesn't need
    contact details. The placeholder shape matches what the Flutter
    chat client expects for system participants."""
    patient_svc = MagicMock()
    patient_svc.fetch_patient_profiles = AsyncMock(return_value={})
    cp_svc = MagicMock()
    cp_svc.fetch_care_provider_profiles = AsyncMock(return_value={})

    chat = {
        "_id": "c-1",
        "participants": [{"id": "admin-1", "type": "admin"}],
        "sender": {"id": "admin-1", "type": "admin"},
        "receivers": [],
    }
    await mod.attach_participant_profiles(
        [chat],
        patient_profile_service=patient_svc,
        care_provider_profile_service=cp_svc,
    )

    assert chat["sender"]["profile"] == {
        "first_name": "Support",
        "last_name": "Team",
        "profile_picture": None,
    }


@pytest.mark.asyncio
async def test_attach_participant_profiles_unknown_type_falls_back_to_unknown_user():
    """Defensive: future participant types (bots, integrations) still
    get a non-null profile so the no-fallback contract holds."""
    patient_svc = MagicMock()
    patient_svc.fetch_patient_profiles = AsyncMock(return_value={})
    cp_svc = MagicMock()
    cp_svc.fetch_care_provider_profiles = AsyncMock(return_value={})

    chat = {
        "_id": "c-1",
        "participants": [{"id": "bot-1", "type": "future_bot"}],
        "sender": {"id": "bot-1", "type": "future_bot"},
        "receivers": [],
    }
    await mod.attach_participant_profiles(
        [chat],
        patient_profile_service=patient_svc,
        care_provider_profile_service=cp_svc,
    )

    assert chat["sender"]["profile"]["first_name"] == "Unknown"


@pytest.mark.asyncio
async def test_attach_participant_profiles_handles_chat_with_no_sender():
    """Edge: an aggregated chat doc where sender lookup returned None
    (the user isn't in the chat — shouldn't happen, but defensive)."""
    patient_svc = MagicMock()
    patient_svc.fetch_patient_profiles = AsyncMock(return_value={})
    cp_svc = MagicMock()
    cp_svc.fetch_care_provider_profiles = AsyncMock(return_value={})

    chat = {
        "_id": "c-1",
        "participants": [],
        "sender": None,
        "receivers": [],
    }
    await mod.attach_participant_profiles(
        [chat],
        patient_profile_service=patient_svc,
        care_provider_profile_service=cp_svc,
    )
    # Just shouldn't raise.
    assert chat["sender"] is None
