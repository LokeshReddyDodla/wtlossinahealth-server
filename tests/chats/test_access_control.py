"""Tests for the chat access-control pre-work.

These tests cover the seams introduced by the security fix:
- :meth:`ChatManagementService.is_user_in_chat` — the query shape used by
  every callsite.
- :func:`lib.services.socketio_service._authorize_chat_access` — the
  identity + participation gate on Socket.IO event handlers.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

# Force-load lib.models first to break a pre-existing circular import:
# ``lib.models.patient`` does a top-level ``from lib.services.chat...
# import ChatManagementService``, while the chat service imports
# ``lib.models.care_provider``. Importing the models package first warms
# the SQLAlchemy registry and resolves the cycle before the service loads.
import lib.models  # noqa: F401,E402
from lib.models.patient import Patient  # noqa: F401,E402
from lib.services.chat.chat_management_service import ChatManagementService  # noqa: E402


def _make_chat_service_with_fake_mongo(find_one_return):
    """Build a ChatManagementService whose mongo_store.db['chats'].find_one
    returns ``find_one_return``. Patching ``get_mongo_store`` at import time
    is brittle because the service captures the function at import, so we
    just swap ``self.mongo_store`` directly."""
    fake_collection = MagicMock()
    fake_collection.find_one = AsyncMock(return_value=find_one_return)
    fake_store = MagicMock()
    fake_store.db = {"chats": fake_collection}

    svc = ChatManagementService()
    svc.mongo_store = fake_store
    return svc, fake_collection


# --- is_user_in_chat -------------------------------------------------------


@pytest.mark.asyncio
async def test_is_user_in_chat_true_when_participant():
    svc, collection = _make_chat_service_with_fake_mongo({"_id": "chat-1"})

    assert await svc.is_user_in_chat("chat-1", "user-a") is True

    collection.find_one.assert_awaited_once()
    args, _kwargs = collection.find_one.call_args
    query = args[0]
    assert query == {"_id": "chat-1", "participants.id": "user-a"}


@pytest.mark.asyncio
async def test_is_user_in_chat_false_when_not_participant():
    svc, _ = _make_chat_service_with_fake_mongo(None)
    assert await svc.is_user_in_chat("chat-1", "intruder") is False


@pytest.mark.asyncio
async def test_is_user_in_chat_false_when_chat_missing():
    """Non-existent chat and not-a-participant are indistinguishable on
    purpose — both return False so we never leak chat existence."""
    svc, _ = _make_chat_service_with_fake_mongo(None)
    assert await svc.is_user_in_chat("does-not-exist", "user-a") is False


# --- _authorize_chat_access (Socket.IO) ----------------------------------


@pytest.fixture
def fake_sio(monkeypatch):
    """Replace the module-level Socket.IO server with a fake whose
    ``get_session`` and ``emit`` are AsyncMocks we can assert on."""
    from lib.services import socketio_service

    fake = MagicMock()
    fake.get_session = AsyncMock(return_value={"user_id": "auth-user"})
    fake.emit = AsyncMock()
    monkeypatch.setattr(socketio_service, "sio", fake)
    return fake


@pytest.fixture
def fake_chat_management(monkeypatch):
    from lib.services import socketio_service

    svc = MagicMock()
    svc.is_user_in_chat = AsyncMock(return_value=True)
    monkeypatch.setattr(socketio_service, "chat_management_service", svc)
    return svc


@pytest.mark.asyncio
async def test_authorize_rejects_when_no_session(
    fake_sio, fake_chat_management
):
    from lib.services.socketio_service import _authorize_chat_access

    fake_sio.get_session = AsyncMock(return_value=None)

    result = await _authorize_chat_access(
        sid="sid-1", chat_id="chat-1", claimed_user_id="auth-user"
    )

    assert result is None
    fake_sio.emit.assert_awaited_once()
    args, kwargs = fake_sio.emit.call_args
    assert args[0] == "error"
    assert "Unauthenticated" in args[1]["message"]
    assert kwargs == {"room": "sid-1"}
    fake_chat_management.is_user_in_chat.assert_not_called()


@pytest.mark.asyncio
async def test_authorize_rejects_spoofed_sender(
    fake_sio, fake_chat_management
):
    """Authenticated as auth-user but payload claims to be someone-else."""
    from lib.services.socketio_service import _authorize_chat_access

    result = await _authorize_chat_access(
        sid="sid-1", chat_id="chat-1", claimed_user_id="someone-else"
    )

    assert result is None
    fake_sio.emit.assert_awaited_once()
    err = fake_sio.emit.call_args.args[1]["message"]
    assert "does not match" in err
    fake_chat_management.is_user_in_chat.assert_not_called()


@pytest.mark.asyncio
async def test_authorize_rejects_non_participant(
    fake_sio, fake_chat_management
):
    from lib.services.socketio_service import _authorize_chat_access

    fake_chat_management.is_user_in_chat = AsyncMock(return_value=False)

    result = await _authorize_chat_access(
        sid="sid-1", chat_id="chat-1", claimed_user_id="auth-user"
    )

    assert result is None
    fake_sio.emit.assert_awaited_once()
    assert "Not a participant" in fake_sio.emit.call_args.args[1]["message"]


@pytest.mark.asyncio
async def test_authorize_returns_user_when_valid(
    fake_sio, fake_chat_management
):
    from lib.services.socketio_service import _authorize_chat_access

    result = await _authorize_chat_access(
        sid="sid-1", chat_id="chat-1", claimed_user_id="auth-user"
    )

    assert result == "auth-user"
    fake_sio.emit.assert_not_called()
    fake_chat_management.is_user_in_chat.assert_awaited_once_with(
        "chat-1", "auth-user"
    )
