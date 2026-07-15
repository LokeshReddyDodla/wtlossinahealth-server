"""Companion Phase 3 — the ask→log→analyze closed loop.

The agent asks the user to log data (pending_data_request); the event-driven
monitor matches the logged entity and posts its analysis INTO the chat thread.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lib.ai_foundation.memory.base import ThreadSummary
from lib.workers.tasks.proactive_monitor.event_scan import _consume_pending_request


def _summary(entity: str = "meal", *, expired: bool = False) -> ThreadSummary:
    delta = timedelta(hours=-1) if expired else timedelta(hours=23)
    return ThreadSummary(
        thread_id="bot:patient:p1", summary="", turn_count=4,
        pending_data_request={
            "entity_type": entity,
            "asked_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": (datetime.now(timezone.utc) + delta).isoformat(),
        },
    )


def _memory(summary: ThreadSummary | None):
    mem = MagicMock()
    mem.get_thread_summary = AsyncMock(return_value=summary)
    mem.save_thread_summary = AsyncMock()
    mem.update_thread_summary_fields = AsyncMock()
    mem.append_turns_batch = AsyncMock()
    return mem


@pytest.mark.asyncio
async def test_match_appends_turn_clears_and_routes():
    mem = _memory(_summary("meal"))
    with patch("lib.workers.tasks.proactive_monitor.event_scan.container") as c:
        c.resolve.return_value = mem
        ok = await _consume_pending_request("bot:patient:p1", "meal", "Nice lunch — 32g protein.")
    assert ok is True
    mem.append_turns_batch.assert_awaited_once()
    turns = mem.append_turns_batch.await_args.args[1]
    assert turns[0].role == "assistant"
    assert "32g protein" in turns[0].content
    assert turns[0].metadata["kind"] == "data_request_followup"
    # pending cleared via partial $set — AFTER the turn was appended
    mem.update_thread_summary_fields.assert_awaited_once_with(
        "bot:patient:p1", {"pending_data_request": None},
    )


@pytest.mark.asyncio
async def test_wrong_entity_type_untouched():
    mem = _memory(_summary("smbg"))
    with patch("lib.workers.tasks.proactive_monitor.event_scan.container") as c:
        c.resolve.return_value = mem
        ok = await _consume_pending_request("bot:patient:p1", "meal", "body")
    assert ok is False
    mem.append_turns_batch.assert_not_awaited()
    mem.update_thread_summary_fields.assert_not_awaited()  # pending stays for the right event


@pytest.mark.asyncio
async def test_expired_request_cleared_but_no_continuation():
    mem = _memory(_summary("meal", expired=True))
    with patch("lib.workers.tasks.proactive_monitor.event_scan.container") as c:
        c.resolve.return_value = mem
        ok = await _consume_pending_request("bot:patient:p1", "meal", "body")
    assert ok is False
    mem.append_turns_batch.assert_not_awaited()
    mem.update_thread_summary_fields.assert_awaited_once_with(
        "bot:patient:p1", {"pending_data_request": None},
    )  # stale ask cleaned up


@pytest.mark.asyncio
async def test_no_pending_or_no_entity_is_noop():
    mem = _memory(ThreadSummary(thread_id="t", summary="", turn_count=2))
    with patch("lib.workers.tasks.proactive_monitor.event_scan.container") as c:
        c.resolve.return_value = mem
        assert await _consume_pending_request("t", "meal", "b") is False
        assert await _consume_pending_request("t", None, "b") is False
    mem.append_turns_batch.assert_not_awaited()


@pytest.mark.asyncio
async def test_persistence_record_and_compaction_preserve():
    """record_pending_request writes TTL'd state; compaction must not wipe it."""
    from lib.ai_foundation.agents.core.persistence_service import PersistenceService

    mem = MagicMock()
    mem.get_thread_summary = AsyncMock(return_value=None)
    mem.update_thread_summary_fields = AsyncMock()
    svc = PersistenceService(memory=mem, gateway=MagicMock())
    await svc.record_pending_request(thread_id="t1", entity_type="meal")

    fields = mem.update_thread_summary_fields.await_args.args[1]
    p = fields["pending_data_request"]
    assert p["entity_type"] == "meal"
    assert datetime.fromisoformat(p["expires_at"]) > datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_zero_insight_ack_still_closes_the_loop():
    """When the scan finds nothing, a matching pending request still gets a
    warm ack turn instead of silence."""
    from lib.workers.tasks.proactive_monitor.event_scan import _ack_body

    mem = _memory(_summary("meal"))
    with patch("lib.workers.tasks.proactive_monitor.event_scan.container") as c:
        c.resolve.return_value = mem
        ok = await _consume_pending_request("bot:patient:p1", "meal", _ack_body("meal"))
    assert ok is True
    turns = mem.append_turns_batch.await_args.args[1]
    assert "Got your meal" in turns[0].content
    mem.update_thread_summary_fields.assert_awaited_once_with(
        "bot:patient:p1", {"pending_data_request": None},
    )
    # unknown entity falls back to a generic word, never KeyErrors
    assert "log" in _ack_body("unknown_thing") and "log" in _ack_body(None)


def test_extract_open_question_handles_hindi_danda():
    """Devanagari '।' ends sentences — without splitting on it, the whole
    Hindi paragraph got captured as 'the question'."""
    from lib.ai_foundation.agents.core.persistence_service import PersistenceService

    msg = "आपका ग्लूकोज़ आज स्थिर रहा। नींद भी ठीक थी। क्या आपने आज खाना लॉग किया?"
    q = PersistenceService.extract_open_question(msg)
    assert q == "क्या आपने आज खाना लॉग किया?"
    # English behaviour unchanged
    q2 = PersistenceService.extract_open_question("All good. Did you sleep well?")
    assert q2 == "Did you sleep well?"
    assert PersistenceService.extract_open_question("All good today.") is None
