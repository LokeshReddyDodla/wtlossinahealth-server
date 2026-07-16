"""Silent pipeline retry — one re-attempt before any patient-visible error.

Transient provider failures (timeouts, brownouts) were surfacing as the
canned error on the FIRST hiccup; a turn is side-effect free until success
(save + background tasks run after), so one full retry is safe.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from lib.ai_foundation.agents.health_query.agent import HealthQueryAgent, _PipelineContext
from lib.ai_foundation.agents.state import AgentContext, AgentInput


def _agent() -> HealthQueryAgent:
    return HealthQueryAgent(
        gateway=MagicMock(), memory=None, prompts=None, event_bus=None,
        context_loader=None, reasoning_engine=None, coordinator=None,
        persistence=None, fact_extractor=None,
    )


def _input() -> AgentInput:
    pid = str(uuid4())
    return AgentInput(
        message="how is my glucose?",
        context=AgentContext(
            patient_id=pid, user_id=pid, user_role="patient",
            thread_id="retry-test", patient_ids=[pid],
        ),
    )


def _clarification_pc(agent) -> _PipelineContext:
    """A pipeline context that short-circuits run() at the clarification exit."""
    import time as _time
    from datetime import datetime, timezone

    intent = MagicMock()
    intent.memory_action = None
    intent.is_ready = False
    intent.clarification_msg = "Which day did you mean?"
    intent.suggestions = []
    return _PipelineContext(
        pipeline_start=_time.perf_counter(),
        user_timestamp=datetime.now(timezone.utc),
        trace_id="trc_test",
        ctx=MagicMock(response_language="en"),
        intent=intent,
        meta=None,
    )


class TestRunRetry:
    @pytest.mark.asyncio
    async def test_transient_failure_retried_silently(self, monkeypatch):
        agent = _agent()
        pc = _clarification_pc(agent)
        init = AsyncMock(side_effect=[TimeoutError("provider timeout"), pc])
        monkeypatch.setattr(agent, "_init_pipeline", init)
        monkeypatch.setattr(agent, "_save_turn", AsyncMock(return_value=None))
        with patch("asyncio.sleep", new=AsyncMock()):
            out = await agent.run(_input())
        assert init.await_count == 2
        assert out.message == "Which day did you mean?"  # real answer, no canned error

    @pytest.mark.asyncio
    async def test_second_failure_surfaces_canned_error_once(self, monkeypatch):
        agent = _agent()
        init = AsyncMock(side_effect=TimeoutError("still down"))
        monkeypatch.setattr(agent, "_init_pipeline", init)
        with patch("asyncio.sleep", new=AsyncMock()):
            out = await agent.run(_input())
        assert init.await_count == 2  # exactly one retry, never more
        assert "having trouble" in out.message
        assert out.is_ready is False

    @pytest.mark.asyncio
    async def test_success_never_retries(self, monkeypatch):
        agent = _agent()
        pc = _clarification_pc(agent)
        init = AsyncMock(return_value=pc)
        monkeypatch.setattr(agent, "_init_pipeline", init)
        monkeypatch.setattr(agent, "_save_turn", AsyncMock(return_value=None))
        out = await agent.run(_input())
        assert init.await_count == 1
        assert out.message == "Which day did you mean?"


class TestStreamInitRetry:
    @pytest.mark.asyncio
    async def test_pre_content_init_retried(self, monkeypatch):
        agent = _agent()
        pc = _clarification_pc(agent)
        init = AsyncMock(side_effect=[TimeoutError("blip"), pc])
        monkeypatch.setattr(agent, "_init_pipeline", init)
        monkeypatch.setattr(agent, "_save_turn", AsyncMock(return_value=None))
        with patch("asyncio.sleep", new=AsyncMock()):
            events = [e async for e in agent.run_stream(_input())]
        assert init.await_count == 2
        joined = "".join(events)
        assert "Which day did you mean?" in joined
        assert "agent_error" not in joined

    @pytest.mark.asyncio
    async def test_double_init_failure_yields_error_event(self, monkeypatch):
        agent = _agent()
        init = AsyncMock(side_effect=TimeoutError("still down"))
        monkeypatch.setattr(agent, "_init_pipeline", init)
        with patch("asyncio.sleep", new=AsyncMock()):
            events = [e async for e in agent.run_stream(_input())]
        assert init.await_count == 2
        joined = "".join(events)
        # TimeoutError routes to the pipeline_timeout handler; other
        # exceptions to agent_error — either way the client gets an error event.
        assert "event: error" in joined
