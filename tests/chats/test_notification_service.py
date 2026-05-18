"""ChatNotificationService — socket fan-out tests.

The notable invariant: when an event is triggered BY a participant (e.g.
mark-as-read), the socket fan-out skips that participant via
``exclude_user_id``. Matches the FCM path which already filters the
sender. Removes a wasted round-trip per mark-as-read.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import lib.models  # noqa: F401,E402
from lib.models.patient import Patient  # noqa: F401,E402

from lib.services.chat.chat_notification_service import (  # noqa: E402
    ChatNotificationService,
)


@pytest.fixture
def svc():
    s = ChatNotificationService()
    s.participant_service = MagicMock()
    s.participant_service.fetch_chat_participants = AsyncMock(
        return_value=[
            {"id": "user-a", "type": "patient"},
            {"id": "user-b", "type": "care_provider"},
            {"id": "user-c", "type": "admin"},
        ]
    )
    return s


@pytest.mark.asyncio
async def test_notify_participants_emits_to_everyone_by_default(svc):
    with patch("lib.services.socketio_service.sio") as sio:
        sio.emit = AsyncMock()
        await svc.notify_participants(
            message_key="some_event", data={"x": 1}, chat_id="c-1"
        )
    rooms = [call.kwargs["room"] for call in sio.emit.await_args_list]
    assert set(rooms) == {"user-a", "user-b", "user-c"}


@pytest.mark.asyncio
async def test_notify_participants_skips_excluded_user(svc):
    """The user who triggered the event gets skipped — no echo back."""
    with patch("lib.services.socketio_service.sio") as sio:
        sio.emit = AsyncMock()
        await svc.notify_participants(
            message_key="message_marked_as_read",
            data={"chat_id": "c-1", "user_id": "user-b"},
            chat_id="c-1",
            exclude_user_id="user-b",
        )
    rooms = [call.kwargs["room"] for call in sio.emit.await_args_list]
    assert set(rooms) == {"user-a", "user-c"}
    assert "user-b" not in rooms


@pytest.mark.asyncio
async def test_notify_participants_exclude_unknown_id_is_noop(svc):
    """Excluding a user who isn't in the chat doesn't break the fan-out."""
    with patch("lib.services.socketio_service.sio") as sio:
        sio.emit = AsyncMock()
        await svc.notify_participants(
            message_key="some_event",
            data=None,
            chat_id="c-1",
            exclude_user_id="not-a-participant",
        )
    rooms = [call.kwargs["room"] for call in sio.emit.await_args_list]
    assert set(rooms) == {"user-a", "user-b", "user-c"}


@pytest.mark.asyncio
async def test_notify_participants_exclude_handles_id_type_coercion(svc):
    """Participant ids may come back as plain strings; exclude id may
    come in as a UUID or other type. Compare as strings."""
    svc.participant_service.fetch_chat_participants = AsyncMock(
        return_value=[
            {"id": "user-a", "type": "patient"},
            {"id": 12345, "type": "admin"},  # numeric, intentionally weird
        ]
    )
    with patch("lib.services.socketio_service.sio") as sio:
        sio.emit = AsyncMock()
        await svc.notify_participants(
            message_key="some_event",
            data=None,
            chat_id="c-1",
            exclude_user_id=12345,
        )
    rooms = [call.kwargs["room"] for call in sio.emit.await_args_list]
    assert rooms == ["user-a"]
