"""Tests for the refactored Health Query Agent (thin orchestrator)."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from lib.ai_foundation.agents.health_query.agent import HealthQueryAgent
from lib.ai_foundation.agents.health_query.contracts import (
    HealthDataType, QueryIntent, QueryResponse, SuggestedAction, DateRange,
)
from lib.ai_foundation.agents.health_query.context_loader import ContextLoader, AgentContext
from lib.ai_foundation.agents.health_query.data_service import HealthDataService
from lib.ai_foundation.agents.health_query.persistence_service import PersistenceService
from lib.ai_foundation.agents.health_query.fact_extractor import FactExtractor
from lib.ai_foundation.agents.state import AgentContext as InputContext, AgentInput, AgentOutput
from lib.ai_foundation.models.gateway import LLMResponse, LLMUsage
from lib.ai_foundation.models.pricing import CostBreakdown
from lib.ai_foundation.prompts.registry import PromptRegistry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _mock_gateway():
    gw = AsyncMock()
    intent = QueryIntent(
        is_ready=True, data_types=[HealthDataType.CGM_RANGE], confidence=0.9,
        suggestions=[SuggestedAction(label="More", description="Show more")],
    )
    meta = LLMResponse(
        content="{}", model_id="gpt-4.1-mini",
        usage=LLMUsage(input_tokens=500, output_tokens=100, cost=CostBreakdown(total_cost=0.002)),
        latency_ms=300, trace_id="trc_test",
    )
    gw.extract = AsyncMock(return_value=(intent, meta))
    gw.complete = AsyncMock(return_value=LLMResponse(
        content="Your glucose averaged 145 mg/dL.", model_id="gpt-5.1",
        usage=LLMUsage(input_tokens=1000, output_tokens=200, cost=CostBreakdown(total_cost=0.01)),
    ))
    return gw


def _mock_context_loader():
    loader = AsyncMock(spec=ContextLoader)
    loader.load = AsyncMock(return_value=AgentContext(
        facts=[{"key": "goal", "value": "fat loss"}],
        history=[],
        thread_summary=None,
        patient_names={"p123": "Ahmed Khan"},
    ))
    return loader


def _mock_data_service():
    svc = AsyncMock(spec=HealthDataService)
    svc.fetch = AsyncMock(return_value="CGM RANGE STATS (1 entries):\n  - date: 2026-03-24, average_glucose: 145")
    return svc


def _mock_persistence():
    svc = AsyncMock(spec=PersistenceService)
    svc.save_turn = AsyncMock()
    svc.compact_if_needed = AsyncMock()
    return svc


def _mock_fact_extractor():
    ext = AsyncMock(spec=FactExtractor)
    ext.extract_if_needed = AsyncMock()
    return ext


def _make_agent(**overrides):
    prompts = PromptRegistry()
    prompts.register_directory(Path("lib/ai_foundation/agents/health_query/prompts"), namespace="health_query")
    return HealthQueryAgent(
        gateway=overrides.get("gateway", _mock_gateway()),
        prompts=overrides.get("prompts", prompts),
        context_loader=overrides.get("context_loader", _mock_context_loader()),
        data_service=overrides.get("data_service", _mock_data_service()),
        persistence=overrides.get("persistence", _mock_persistence()),
        fact_extractor=overrides.get("fact_extractor", _mock_fact_extractor()),
    )


def _make_input(message="How were my sugars?", **kwargs):
    return AgentInput(
        message=message,
        context=InputContext(
            patient_id=kwargs.get("patient_id", "p123"),
            user_id=kwargs.get("user_id", "u123"),
            user_role=kwargs.get("user_role", "patient"),
            thread_id=kwargs.get("thread_id", "t123"),
            patient_ids=kwargs.get("patient_ids", ["p123"]),
        ),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestContracts:
    def test_ready_intent(self):
        intent = QueryIntent(is_ready=True, data_types=[HealthDataType.CGM_RANGE], confidence=0.9)
        assert intent.is_ready
        assert len(intent.data_types) == 1

    def test_not_ready_intent(self):
        intent = QueryIntent(is_ready=False, clarification_msg="What time period?", confidence=0.3)
        assert not intent.is_ready

    def test_query_response_backward_compat(self):
        resp = QueryResponse(is_ready=True, user_message="test", message="response", trace_id="trc_1")
        assert resp.type == "response"


class TestAgent:
    def test_agent_id(self):
        assert _make_agent().agent_id == "health_query_v3"

    @pytest.mark.asyncio
    async def test_run_ready(self):
        agent = _make_agent()
        output = await agent.run(_make_input())
        assert output.is_ready
        assert "145" in output.message
        assert len(output.suggestions) >= 1

    @pytest.mark.asyncio
    async def test_run_not_ready(self):
        gw = _mock_gateway()
        gw.extract = AsyncMock(return_value=(
            QueryIntent(is_ready=False, clarification_msg="What time?", confidence=0.3,
                        suggestions=[SuggestedAction(label="Today", description="Show today")]),
            LLMResponse(content="{}", model_id="m", usage=LLMUsage(cost=CostBreakdown(total_cost=0.001))),
        ))
        agent = _make_agent(gateway=gw)
        output = await agent.run(_make_input("how am I"))
        assert not output.is_ready
        assert "time" in output.message.lower()
        # Gateway.complete should NOT have been called
        gw.complete.assert_not_called()

    @pytest.mark.asyncio
    async def test_run_saves_turns(self):
        persistence = _mock_persistence()
        agent = _make_agent(persistence=persistence)
        await agent.run(_make_input())
        persistence.save_turn.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_handles_error(self):
        gw = _mock_gateway()
        gw.extract = AsyncMock(side_effect=Exception("LLM down"))
        agent = _make_agent(gateway=gw)
        output = await agent.run(_make_input())
        assert not output.is_ready
        assert "trouble" in output.message.lower()

    @pytest.mark.asyncio
    async def test_run_without_services(self):
        """Agent works even with no services (graceful degradation)."""
        agent = HealthQueryAgent(gateway=_mock_gateway(), prompts=PromptRegistry())
        agent.prompts.register_directory(Path("lib/ai_foundation/agents/health_query/prompts"), namespace="health_query")
        output = await agent.run(_make_input())
        assert output.is_ready  # still works, just with "No data source"

    @pytest.mark.asyncio
    async def test_run_care_provider(self):
        agent = _make_agent()
        output = await agent.run(_make_input(user_role="care_provider", patient_ids=["p1", "p2"]))
        assert output.is_ready

    def test_to_query_response(self):
        agent = _make_agent()
        inp = _make_input()
        out = AgentOutput(message="Response.", is_ready=True, suggestions=[],
                          data={"data_types": ["cgm_range_stats"], "confidence": 0.9},
                          trace_id="trc_1", cost_usd=0.005)
        resp = agent.to_query_response(inp, out)
        assert resp.is_ready
        assert resp.trace_id == "trc_1"
        assert resp.final_response == "Response."


class TestStreaming:
    @pytest.mark.asyncio
    async def test_stream_ready(self):
        gw = _mock_gateway()
        async def mock_stream(**kwargs):
            yield MagicMock(delta="Hello ", finished=False)
            yield MagicMock(delta="world.", finished=False)
            yield MagicMock(delta="", finished=True, full_content="Hello world.", usage=None)
        gw.stream = mock_stream

        agent = _make_agent(gateway=gw)
        events = []
        async for e in agent.run_stream(_make_input()):
            events.append(e)

        types = [e.split("event: ")[1].split("\n")[0] for e in events if "event:" in e]
        assert "status" in types
        assert "intent" in types
        assert "token" in types
        assert "done" in types

    @pytest.mark.asyncio
    async def test_stream_not_ready(self):
        gw = _mock_gateway()
        gw.extract = AsyncMock(return_value=(
            QueryIntent(is_ready=False, clarification_msg="What period?", confidence=0.2),
            LLMResponse(content="{}", model_id="m", usage=LLMUsage(cost=CostBreakdown())),
        ))
        agent = _make_agent(gateway=gw)
        events = []
        async for e in agent.run_stream(_make_input()):
            events.append(e)
        all_text = "".join(events)
        assert "What period?" in all_text
        assert "fetching_data" not in all_text

    @pytest.mark.asyncio
    async def test_stream_error(self):
        gw = _mock_gateway()
        gw.extract = AsyncMock(side_effect=Exception("boom"))
        agent = _make_agent(gateway=gw)
        events = []
        async for e in agent.run_stream(_make_input()):
            events.append(e)
        assert any("error" in e for e in events)


class TestFactExtractor:
    def test_extractor_exists(self):
        """FactExtractor now always runs LLM — no keyword heuristic to test."""
        from lib.ai_foundation.agents.health_query.fact_extractor import FactExtractor
        ext = FactExtractor()
        assert hasattr(ext, "extract_if_needed")


class TestPromptLoading:
    def test_prompts_load(self):
        registry = PromptRegistry()
        count = registry.register_directory(Path("lib/ai_foundation/agents/health_query/prompts"), namespace="hq")
        assert count >= 4
        assert "hq_system_patient" in registry
        assert "hq_system_admin" in registry

    def test_system_prompt_renders(self):
        registry = PromptRegistry()
        registry.register_directory(Path("lib/ai_foundation/agents/health_query/prompts"), namespace="hq")
        template = registry.get("hq_system_patient")
        rendered = template.render(current_time="2026-03-24 10:00 UTC")
        assert "2026-03-24" in rendered
