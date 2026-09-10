"""SupportAssistantService — when the bot may speak, and what it records.

Invariants under test:
- Only patient tickets, only the patient's own messages, only while no
  human agent is a chat participant, only under the reply budget, only when
  the feature is enabled for that patient.
- The reply is posted through ChatMessagingService as the bot sender.
- Ticket bookkeeping ``$set``s ``assistant.*`` only, targeted by ``_id``,
  and never touches ``status``.
- ``schedule_reply`` ignores non-support chats and the bot's own messages.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import lib.models  # noqa: F401  (warm the import graph, see other support tests)
from lib.ai_foundation.agents.state import AgentOutput
from lib.ai_foundation.agents.support_assistant import SupportSnapshot
from lib.ai_foundation.config import settings
from lib.core.constants import SUPPORT_ASSISTANT_SENDER_ID
from lib.models.patient import Patient  # noqa: F401
from lib.services.support import support_assistant_service as module
from lib.services.support.support_assistant_service import (
    SupportAssistantService,
    schedule_reply,
)

PATIENT = "11111111-1111-4111-8111-111111111111"
AGENT = "22222222-2222-4222-8222-222222222222"


def _ticket(**overrides):
    t = {
        "_id": "ticket-1",
        "chat_id": "chat-1",
        "scope": "product",
        "requester_id": PATIENT,
        "requester_type": "patient",
        "status": "open",
    }
    t.update(overrides)
    return t


def _chat(participants=None):
    return {
        "_id": "chat-1",
        "kind": "support",
        "participants": participants or [{"id": PATIENT, "type": "patient"}],
    }


def _message(sender=PATIENT, content="my sensor stopped", _id="msg-9"):
    return {"_id": _id, "chat_id": "chat-1", "sender_id": sender, "content": content}


def _mongo(ticket, history_rows=None):
    tickets = MagicMock()
    tickets.find_one = AsyncMock(return_value=ticket)
    tickets.update_one = AsyncMock()

    cursor = MagicMock()
    cursor.sort = MagicMock(return_value=cursor)
    cursor.limit = MagicMock(return_value=cursor)
    cursor.to_list = AsyncMock(return_value=history_rows or [])
    messages = MagicMock()
    messages.find = MagicMock(return_value=cursor)

    store = MagicMock()
    store.db = {"support_tickets": tickets, "chat_messages": messages}
    return store, tickets, messages


def _service(ticket, *, enabled=True, history_rows=None, output=None, snapshot=None):
    store, tickets, messages = _mongo(ticket, history_rows)
    agent = MagicMock()
    agent.run = AsyncMock(
        return_value=output
        or AgentOutput(
            message="Try Sync Now under Connected Apps.",
            data={
                "category": "cgm_sensor",
                "urgency": "high",
                "needs_human": False,
                "summary": "Sensor stopped; told to sync.",
                "handling_mode": "answered",
            },
        )
    )
    snapshot_service = MagicMock()
    snapshot_service.build = AsyncMock(return_value=snapshot or SupportSnapshot(timezone="Asia/Kolkata"))
    chat_messaging = MagicMock()
    chat_messaging.add_message = AsyncMock()
    toggles = MagicMock()
    toggles.is_enabled_for_patient = AsyncMock(return_value=enabled)

    svc = SupportAssistantService(
        agent=agent,
        snapshot_service=snapshot_service,
        chat_messaging_service=chat_messaging,
        feature_toggles=toggles,
        mongo_store=store,
    )
    return svc, dict(agent=agent, tickets=tickets, messages=messages, chat=chat_messaging, toggles=toggles, snapshot=snapshot_service)


# --- happy path ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_replies_as_bot_and_records_triage_on_ticket():
    rows = [  # newest first, as Mongo returns them
        {"sender_id": SUPPORT_ASSISTANT_SENDER_ID, "content": "Hello, how can I help?"},
        {"sender_id": PATIENT, "content": "hi"},
    ]
    svc, parts = _service(_ticket(), history_rows=rows)

    result = await svc.handle(chat=_chat(), message=_message())

    assert result == {"message": "Try Sync Now under Connected Apps.", "data": parts["agent"].run.return_value.data}

    # Reply posted through the chat path as the bot sender.
    posted = parts["chat"].add_message.await_args.args[0]
    assert posted.sender_id == SUPPORT_ASSISTANT_SENDER_ID
    assert posted.chat_id == "chat-1"
    assert posted.content == "Try Sync Now under Connected Apps."
    assert posted.severity == "low"

    # Agent got the patient context, oldest-first history, and the snapshot.
    agent_input = parts["agent"].run.await_args.args[0]
    assert agent_input.message == "my sensor stopped"
    assert agent_input.context.patient_id == PATIENT
    assert agent_input.context.thread_id == "support:ticket-1"
    assert agent_input.context.timezone == "Asia/Kolkata"
    assert agent_input.metadata["history"] == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "Hello, how can I help?"},
    ]
    assert agent_input.metadata["snapshot"]["timezone"] == "Asia/Kolkata"

    # History query excludes the message being answered.
    find_query = parts["messages"].find.call_args.args[0]
    assert find_query == {"chat_id": "chat-1", "_id": {"$ne": "msg-9"}}

    # Ticket bookkeeping: $set assistant.* only, by _id, plus reply_count $inc.
    filt, update = parts["tickets"].update_one.await_args.args
    assert filt == {"_id": "ticket-1"}
    assert set(update) == {"$set", "$inc"}
    assert all(k.startswith("assistant.") for k in update["$set"])
    assert update["$set"]["assistant.category"] == "cgm_sensor"
    assert update["$set"]["assistant.needs_human"] is False
    assert update["$set"]["assistant.summary"] == "Sensor stopped; told to sync."
    assert update["$inc"] == {"assistant.reply_count": 1}
    assert "status" not in update["$set"]


@pytest.mark.asyncio
async def test_urgent_triage_posts_urgent_severity_message():
    out = AgentOutput(message="Call 108 now.", data={"category": "emergency", "urgency": "urgent", "needs_human": True, "summary": "s", "handling_mode": "emergency"})
    svc, parts = _service(_ticket(), output=out)

    await svc.handle(chat=_chat(), message=_message(content="chest pain"))

    assert parts["chat"].add_message.await_args.args[0].severity == "urgent"
    assert parts["tickets"].update_one.await_args.args[1]["$set"]["assistant.needs_human"] is True


@pytest.mark.asyncio
async def test_snapshot_failure_degrades_to_unavailable_sections():
    svc, parts = _service(_ticket())
    parts["snapshot"].build = AsyncMock(side_effect=RuntimeError("pg down"))

    await svc.handle(chat=_chat(), message=_message())

    snap = parts["agent"].run.await_args.args[0].metadata["snapshot"]
    assert "care_team" in snap["lookup_errors"] and "permissions" in snap["lookup_errors"]
    parts["chat"].add_message.assert_awaited_once()


# --- silence rules --------------------------------------------------------------


@pytest.mark.asyncio
async def test_silent_when_no_ticket_for_chat():
    svc, parts = _service(None)
    assert await svc.handle(chat=_chat(), message=_message()) is None
    parts["agent"].run.assert_not_awaited()
    parts["chat"].add_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_silent_on_care_provider_tickets():
    svc, parts = _service(_ticket(requester_type="care_provider", requester_id=AGENT))
    assert await svc.handle(chat=_chat([{"id": AGENT, "type": "care_provider"}]), message=_message(sender=AGENT)) is None
    parts["agent"].run.assert_not_awaited()


@pytest.mark.asyncio
async def test_silent_when_sender_is_not_the_requester():
    svc, parts = _service(_ticket())
    assert await svc.handle(chat=_chat(), message=_message(sender=AGENT)) is None
    assert await svc.handle(chat=_chat(), message=_message(sender=SUPPORT_ASSISTANT_SENDER_ID)) is None
    parts["agent"].run.assert_not_awaited()


@pytest.mark.asyncio
async def test_silent_once_a_human_agent_has_joined():
    svc, parts = _service(_ticket())
    chat = _chat([{"id": PATIENT, "type": "patient"}, {"id": AGENT, "type": "admin"}])
    assert await svc.handle(chat=chat, message=_message()) is None
    parts["agent"].run.assert_not_awaited()


@pytest.mark.asyncio
async def test_bot_as_participant_does_not_count_as_human():
    svc, parts = _service(_ticket())
    chat = _chat([{"id": PATIENT, "type": "patient"}, {"id": SUPPORT_ASSISTANT_SENDER_ID, "type": "admin"}])
    assert await svc.handle(chat=chat, message=_message()) is not None


@pytest.mark.asyncio
async def test_silent_when_reply_budget_exhausted():
    cap = settings.SUPPORT_ASSISTANT_MAX_REPLIES_PER_TICKET
    svc, parts = _service(_ticket(assistant={"reply_count": cap}))
    assert await svc.handle(chat=_chat(), message=_message()) is None
    parts["agent"].run.assert_not_awaited()

    svc, parts = _service(_ticket(assistant={"reply_count": cap - 1}))
    assert await svc.handle(chat=_chat(), message=_message()) is not None


@pytest.mark.asyncio
async def test_silent_when_feature_disabled_for_patient():
    svc, parts = _service(_ticket(), enabled=False)
    assert await svc.handle(chat=_chat(), message=_message()) is None
    parts["toggles"].is_enabled_for_patient.assert_awaited_once()
    parts["agent"].run.assert_not_awaited()


@pytest.mark.asyncio
async def test_agent_exception_is_swallowed_and_nothing_posted():
    svc, parts = _service(_ticket())
    parts["agent"].run = AsyncMock(side_effect=RuntimeError("boom"))
    assert await svc.handle(chat=_chat(), message=_message()) is None
    parts["chat"].add_message.assert_not_awaited()
    parts["tickets"].update_one.assert_not_awaited()


# --- scheduler ------------------------------------------------------------------


def test_schedule_reply_ignores_non_support_and_bot_messages(monkeypatch):
    created = []
    monkeypatch.setattr(module.asyncio, "create_task", lambda coro, **k: created.append(coro))

    schedule_reply(chat={"_id": "c", "kind": "direct"}, message=_message())
    schedule_reply(chat=None, message=_message())
    schedule_reply(chat=_chat(), message=_message(sender=SUPPORT_ASSISTANT_SENDER_ID))
    assert created == []


@pytest.mark.asyncio
async def test_schedule_reply_spawns_task_for_patient_message(monkeypatch):
    svc, parts = _service(_ticket())
    # ``schedule_reply`` imports the container lazily; hand it a stub module
    # so the test never boots the real dependency graph.
    fake_container = MagicMock()
    fake_container.resolve = MagicMock(return_value=svc)
    monkeypatch.setitem(sys.modules, "lib.core.container", SimpleNamespace(container=fake_container))

    schedule_reply(chat=_chat(), message=_message())
    assert module._BACKGROUND_TASKS, "a background task should be tracked"
    task = next(iter(module._BACKGROUND_TASKS))
    await task
    parts["chat"].add_message.assert_awaited_once()
    assert task not in module._BACKGROUND_TASKS
