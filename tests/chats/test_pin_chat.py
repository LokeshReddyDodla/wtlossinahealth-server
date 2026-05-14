"""toggle_pin_chat — verifies the chat_list_updated event carries the
rich payload per the unified event contract (spec A).

Pin is user-private (only the actor's view changes), so the event scope
stays at the actor's user_id room.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import lib.models  # noqa: F401,E402
from lib.models.patient import Patient  # noqa: F401,E402

from lib.services.chat.chat_management_service import (  # noqa: E402
    ChatManagementService,
)


@pytest.mark.asyncio
async def test_toggle_pin_emits_rich_chat_list_updated_payload():
    svc = ChatManagementService()

    fake_chats = MagicMock()
    fake_chats.find_one = AsyncMock(
        return_value={
            "_id": "chat-1",
            "participants": [
                {"id": "user-a", "is_pinned": False, "type": "patient"},
            ],
        }
    )
    fake_chats.update_one = AsyncMock()
    fake_store = MagicMock()
    fake_store.db = {"chats": fake_chats}
    svc.mongo_store = fake_store

    with patch("lib.services.socketio_service.sio") as sio:
        sio.emit = AsyncMock()
        await svc.toggle_pin_chat("chat-1", "user-a")

    sio.emit.assert_awaited_once()
    args, kwargs = sio.emit.call_args
    event_key, payload = args[0], args[1]
    assert event_key == "chat_list_updated"
    assert payload == {
        "chat_id": "chat-1",
        "change": "pinned",
        "is_pinned": True,  # was False, toggled
        "user_id": "user-a",
    }
    assert kwargs == {"room": "user-a"}


@pytest.mark.asyncio
async def test_toggle_pin_inverts_existing_pinned_state():
    """Already-pinned chat unpins; is_pinned payload reflects new value."""
    svc = ChatManagementService()

    fake_chats = MagicMock()
    fake_chats.find_one = AsyncMock(
        return_value={
            "_id": "chat-1",
            "participants": [
                {"id": "user-a", "is_pinned": True, "type": "patient"},
            ],
        }
    )
    fake_chats.update_one = AsyncMock()
    fake_store = MagicMock()
    fake_store.db = {"chats": fake_chats}
    svc.mongo_store = fake_store

    with patch("lib.services.socketio_service.sio") as sio:
        sio.emit = AsyncMock()
        await svc.toggle_pin_chat("chat-1", "user-a")

    payload = sio.emit.call_args.args[1]
    assert payload["is_pinned"] is False
