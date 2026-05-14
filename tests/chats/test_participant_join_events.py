"""Spec item D — chat_list_updated emissions on roster mutations.

Two distinct ``change`` values cover the same physical event from two
different points of view:

- ``chat_created`` → new participant: 'this is a new chat for you,
  insert it into the inbox'
- ``participants_changed`` → existing participants: 'the receivers list
  changed, refetch'

Both share the same trigger (``add_participant_in_chat`` with a truly
new user) and the same Socket.IO room mechanism.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import lib.models  # noqa: F401,E402
from lib.models.patient import Patient  # noqa: F401,E402

from lib.services.chat.chat_management_service import (  # noqa: E402
    ChatManagementService,
)
from lib.services.chat.chat_participant_service import (  # noqa: E402
    ChatParticipantService,
)


# --- add_participant_in_chat (new joiner) -------------------------------


def _make_participant_svc_with_new_user_path(
    chat_kind="support", existing_ids=None
):
    """Wire a ChatParticipantService whose _is_participant_in_chat returns
    False (forcing the new-participant branch) and whose mongo returns
    the given existing participants + kind."""
    existing_ids = existing_ids or []
    svc = ChatParticipantService()
    fake_chats = MagicMock()

    # _is_participant_in_chat does a projected find_one returning None
    # when not found; _fetch_existing_participant_ids returns the list;
    # _broadcast_participant_join fetches kind. Three find_one calls.
    chat_doc_before = {
        "_id": "chat-1",
        "participants": [{"id": pid} for pid in existing_ids],
    }
    chat_doc_kind = {"_id": "chat-1", "kind": chat_kind}
    fake_chats.find_one = AsyncMock(
        side_effect=[
            None,           # _is_participant_in_chat → False
            chat_doc_before,  # _fetch_existing_participant_ids
            chat_doc_kind,    # _broadcast_participant_join's kind lookup
        ]
    )
    fake_chats.update_one = AsyncMock()

    store = MagicMock()
    store.db = {"chats": fake_chats}
    svc.mongo_store = store
    return svc


@pytest.mark.asyncio
async def test_new_participant_gets_chat_created_event():
    """Agent joining a support chat learns about it via chat_created
    carrying the chat_kind so the client routes to the support inbox."""
    svc = _make_participant_svc_with_new_user_path(
        chat_kind="support", existing_ids=["patient-1"]
    )

    with patch("lib.services.socketio_service.sio") as sio:
        sio.emit = AsyncMock()
        await svc.add_participant_in_chat(
            chat_id="chat-1",
            user_id="admin-1",
            type="admin",
        )

    new_user_emits = [
        call
        for call in sio.emit.await_args_list
        if call.kwargs.get("room") == "admin-1"
    ]
    assert len(new_user_emits) == 1
    payload = new_user_emits[0].args[1]
    assert payload == {
        "chat_id": "chat-1",
        "change": "chat_created",
        "chat_kind": "support",
    }


@pytest.mark.asyncio
async def test_existing_participants_get_participants_changed_event():
    """The patient (already in the chat) gets participants_changed when
    the agent joins, so their UI refetches and renders the agent."""
    svc = _make_participant_svc_with_new_user_path(
        chat_kind="support", existing_ids=["patient-1", "patient-2"]
    )

    with patch("lib.services.socketio_service.sio") as sio:
        sio.emit = AsyncMock()
        await svc.add_participant_in_chat(
            chat_id="chat-1",
            user_id="admin-1",
            type="admin",
        )

    existing_emits = [
        call
        for call in sio.emit.await_args_list
        if call.kwargs.get("room") in ("patient-1", "patient-2")
    ]
    assert len(existing_emits) == 2
    for call in existing_emits:
        assert call.args[1] == {
            "chat_id": "chat-1",
            "change": "participants_changed",
        }


@pytest.mark.asyncio
async def test_new_user_excluded_from_participants_changed_fanout():
    """The new joiner appears in the post-write participants list when
    we read it back. They must NOT also receive a participants_changed
    event (that would duplicate chat_created)."""
    svc = ChatParticipantService()
    fake_chats = MagicMock()
    fake_chats.find_one = AsyncMock(
        side_effect=[
            None,  # _is_participant_in_chat → False
            # _fetch_existing_participant_ids — already includes new user
            # (defensive: timing race could surface this)
            {
                "_id": "chat-1",
                "participants": [
                    {"id": "patient-1"},
                    {"id": "admin-1"},
                ],
            },
            {"_id": "chat-1", "kind": "support"},
        ]
    )
    fake_chats.update_one = AsyncMock()
    store = MagicMock()
    store.db = {"chats": fake_chats}
    svc.mongo_store = store

    with patch("lib.services.socketio_service.sio") as sio:
        sio.emit = AsyncMock()
        await svc.add_participant_in_chat(
            chat_id="chat-1",
            user_id="admin-1",
            type="admin",
        )

    rooms = [c.kwargs.get("room") for c in sio.emit.await_args_list]
    # admin-1 gets exactly ONE event (chat_created), not two.
    assert rooms.count("admin-1") == 1


@pytest.mark.asyncio
async def test_idempotent_re_add_emits_nothing():
    """Adding a participant who already exists is a no-op for the
    notification layer. add_participant_in_chat is called by agent_reply
    on every reply (defensive), so the no-emit path is the hot path."""
    svc = ChatParticipantService()
    fake_chats = MagicMock()
    # _is_participant_in_chat returns truthy → the participant exists.
    fake_chats.find_one = AsyncMock(
        return_value={"_id": "chat-1", "participants": [{"id": "admin-1"}]}
    )
    fake_chats.update_one = AsyncMock()
    store = MagicMock()
    store.db = {"chats": fake_chats}
    svc.mongo_store = store

    with patch("lib.services.socketio_service.sio") as sio:
        sio.emit = AsyncMock()
        await svc.add_participant_in_chat(
            chat_id="chat-1",
            user_id="admin-1",
            type="admin",
        )

    sio.emit.assert_not_called()


# --- create_new_chat (initial chat creation) ---------------------------


@pytest.mark.asyncio
async def test_create_new_chat_emits_chat_created_to_initial_participant():
    """When the chat is genuinely new, the creator's inbox gets a row
    patch — carries chat_kind so the client routes correctly."""
    svc = ChatManagementService()
    store = MagicMock()
    # _find_existing_1on1_chat goes through store.find_document. Even
    # for support kinds we skip that lookup, but mock it as None for
    # safety — the kind=support branch in create_new_chat skips it
    # anyway.
    store.find_document = AsyncMock(return_value=None)
    store.insert_document = AsyncMock()
    svc.mongo_store = store

    with patch("lib.services.socketio_service.sio") as sio:
        sio.emit = AsyncMock()
        new_id = await svc.create_new_chat(
            user_id="patient-1",
            other_user_id="patient-1",
            type="patient",
            is_group=False,
            kind="support",
        )

    sio.emit.assert_awaited_once()
    args, kwargs = sio.emit.call_args
    assert args[0] == "chat_list_updated"
    payload = args[1]
    assert payload["chat_id"] == new_id
    assert payload["change"] == "chat_created"
    assert payload["chat_kind"] == "support"
    assert kwargs == {"room": "patient-1"}


@pytest.mark.asyncio
async def test_create_new_chat_does_not_emit_on_1on1_reactivate():
    """The 1-on-1 reactivate branch returns an existing chat_id and
    flips archive flags. No new chat, so no chat_created event — the
    chat is already in the client's inbox."""
    svc = ChatManagementService()
    store = MagicMock()
    # _find_existing_1on1_chat returns the existing chat → reactivate path
    store.find_document = AsyncMock(
        return_value={"_id": "existing-chat-1"}
    )
    store.insert_document = AsyncMock()
    store.update_document_with_array_filters = AsyncMock()
    svc.mongo_store = store

    with patch("lib.services.socketio_service.sio") as sio:
        sio.emit = AsyncMock()
        chat_id = await svc.create_new_chat(
            user_id="patient-1",
            other_user_id="cp-1",
            type="patient",
            is_group=False,
        )

    assert chat_id == "existing-chat-1"
    sio.emit.assert_not_called()
