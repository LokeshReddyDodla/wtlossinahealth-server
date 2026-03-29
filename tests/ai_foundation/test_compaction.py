"""Tests for conversation compaction hardening — locks, turn counts, timeouts."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lib.ai_foundation.agents.health_query.persistence_service import PersistenceService
from lib.ai_foundation.memory.base import ThreadSummary


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_service(*, turn_count: int = 0, summary_text: str = "", title: str = "") -> PersistenceService:
    memory = AsyncMock()
    gateway = MagicMock()

    summary = ThreadSummary(
        thread_id="t1", summary=summary_text, turn_count=turn_count, title=title,
    )
    memory.get_thread_summary = AsyncMock(return_value=summary)
    memory.save_thread_summary = AsyncMock()
    memory.get_thread_turns = AsyncMock(return_value=[])
    memory.count_thread_turns = AsyncMock(return_value=turn_count)
    memory.append_turns_batch = AsyncMock()

    gateway.complete = AsyncMock(return_value=MagicMock(content="Summary text."))

    svc = PersistenceService(memory=memory, gateway=gateway)
    return svc


# ── Test: Concurrent compaction lock ─────────────────────────────────────


class TestConcurrencyLock:
    @pytest.mark.asyncio
    async def test_second_compaction_skipped(self):
        """If thread is already being compacted, second call should skip."""
        svc = _make_service(turn_count=6)

        # Simulate slow compaction
        original_get_turns = svc._memory.get_thread_turns

        async def slow_get_turns(*args, **kwargs):
            await asyncio.sleep(0.1)
            return []

        svc._memory.get_thread_turns = slow_get_turns

        # Start two concurrent compactions
        task1 = asyncio.create_task(svc.compact_if_needed(thread_id="t1"))
        await asyncio.sleep(0.01)  # let task1 acquire the lock
        task2 = asyncio.create_task(svc.compact_if_needed(thread_id="t1"))

        await asyncio.gather(task1, task2)

        # Lock should be released after both complete
        assert "t1" not in PersistenceService._compacting

    @pytest.mark.asyncio
    async def test_different_threads_not_blocked(self):
        """Compaction on thread A should not block thread B."""
        svc = _make_service(turn_count=6)

        # Both should execute (different thread_ids)
        await asyncio.gather(
            svc.compact_if_needed(thread_id="t1"),
            svc.compact_if_needed(thread_id="t2"),
        )
        assert "t1" not in PersistenceService._compacting
        assert "t2" not in PersistenceService._compacting

    @pytest.mark.asyncio
    async def test_lock_released_on_error(self):
        """Lock must be released even if compaction fails."""
        svc = _make_service(turn_count=6)
        svc._memory.get_thread_turns = AsyncMock(side_effect=RuntimeError("DB down"))

        await svc.compact_if_needed(thread_id="t1")

        # Lock should be released
        assert "t1" not in PersistenceService._compacting


# ── Test: Turn count tracking ────────────────────────────────────────────


class TestTurnCountFromQuery:
    @pytest.mark.asyncio
    async def test_turn_count_from_actual_count(self):
        """compact_if_needed should use count_thread_turns, not sample length."""
        svc = _make_service(turn_count=0, title="Title")  # summary says 0 turns
        # Real count is 6 (from count_thread_turns)
        svc._memory.count_thread_turns = AsyncMock(return_value=6)
        svc._memory.get_thread_turns = AsyncMock(return_value=[
            MagicMock(role="user", content="msg"),
            MagicMock(role="assistant", content="resp"),
        ] * 6)

        await svc.compact_if_needed(thread_id="t1")

        # Should have compacted (6 >= threshold 4, 6 % 2 == 0)
        svc._gateway.complete.assert_called_once()


# ── Test: Compaction threshold config ────────────────────────────────────


class TestCompactionThreshold:
    @pytest.mark.asyncio
    async def test_skips_below_threshold(self):
        """Should not compact when turn_count < COMPACTION_TRIGGER_THRESHOLD."""
        svc = _make_service(turn_count=2)

        await svc.compact_if_needed(thread_id="t1")

        # Gateway.complete should NOT have been called (no LLM summarization)
        svc._gateway.complete.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_off_interval(self):
        """Should not compact when turn_count not divisible by interval."""
        svc = _make_service(turn_count=5)  # 5 % 2 != 0

        await svc.compact_if_needed(thread_id="t1")

        svc._gateway.complete.assert_not_called()

    @pytest.mark.asyncio
    async def test_compacts_at_threshold(self):
        """Should compact when turn_count hits threshold and interval."""
        svc = _make_service(turn_count=4, title="Existing Title")
        svc._memory.get_thread_turns = AsyncMock(return_value=[
            MagicMock(role="user", content="msg"),
            MagicMock(role="assistant", content="resp"),
        ] * 6)  # 12 turns

        await svc.compact_if_needed(thread_id="t1")

        # Gateway.complete should have been called once for summarization (title already exists)
        svc._gateway.complete.assert_called_once()


# ── Test: Background task wrapper ────────────────────────────────────────


class TestBackgroundTaskWrapper:
    @pytest.mark.asyncio
    async def test_timeout_enforced(self):
        """Background task should be cancelled after timeout."""
        from lib.ai_foundation.agents.health_query.agent import HealthQueryAgent

        agent = MagicMock(spec=HealthQueryAgent)
        agent._run_background = HealthQueryAgent._run_background.__get__(agent)

        async def slow_task():
            await asyncio.sleep(10)

        # Should not hang — timeout kicks in
        with patch("lib.ai_foundation.config.settings") as mock_settings:
            mock_settings.BACKGROUND_TASK_TIMEOUT_SECONDS = 0.1
            await agent._run_background(slow_task(), name="test", thread_id="t1")

    @pytest.mark.asyncio
    async def test_exception_caught(self):
        """Background task exceptions should not propagate."""
        from lib.ai_foundation.agents.health_query.agent import HealthQueryAgent

        agent = MagicMock(spec=HealthQueryAgent)
        agent._run_background = HealthQueryAgent._run_background.__get__(agent)

        async def failing_task():
            raise RuntimeError("boom")

        with patch("lib.ai_foundation.config.settings") as mock_settings:
            mock_settings.BACKGROUND_TASK_TIMEOUT_SECONDS = 5.0
            # Should not raise
            await agent._run_background(failing_task(), name="test", thread_id="t1")


# ── Test: Compaction guard ───────────────────────────────────────────────


class TestCompactionGuard:
    @pytest.mark.asyncio
    async def test_skips_if_already_compacted(self):
        """Should not re-compact if summary.turn_count >= current - 1."""
        svc = _make_service(turn_count=6, summary_text="Already summarized.")

        # Summary already exists with turn_count=6, which >= 6-1
        await svc.compact_if_needed(thread_id="t1")

        svc._gateway.complete.assert_not_called()
