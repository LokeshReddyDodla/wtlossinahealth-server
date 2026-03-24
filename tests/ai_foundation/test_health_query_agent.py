"""Tests for the foundation Health Query Agent."""

import json
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

import pytest

from lib.ai_foundation.agents.health_query.agent import HealthQueryAgent, _DATA_TYPE_DOMAINS
from lib.ai_foundation.agents.health_query.contracts import (
    DomainName,
    HealthDataType,
    QueryIntent,
    QueryResponse,
    ResponseMode,
    SuggestedAction,
    DateRange,
)
from lib.ai_foundation.agents.state import AgentContext, AgentInput, AgentOutput
from lib.ai_foundation.models.gateway import LLMResponse, LLMUsage
from lib.ai_foundation.models.pricing import CostBreakdown
from lib.ai_foundation.prompts.registry import PromptRegistry
from lib.ai_foundation.retrieval.base import CompositeResult, RetrievalResult


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------


class TestHealthDataType:
    def test_values(self):
        assert HealthDataType.MEAL.value == "meal"
        assert HealthDataType.CGM_RANGE.value == "cgm_range_stats"

    def test_missing_case_insensitive(self):
        assert HealthDataType("MEAL") == HealthDataType.MEAL

    def test_domain_mapping_complete(self):
        for dt in HealthDataType:
            assert dt.value in _DATA_TYPE_DOMAINS, f"{dt.value} missing from domain mapping"


class TestQueryIntent:
    def test_ready_intent(self):
        intent = QueryIntent(
            is_ready=True,
            data_types=[HealthDataType.CGM_RANGE, HealthDataType.CGM_SUMMARY],
            confidence=0.95,
            suggestions=[SuggestedAction(label="Details", description="Show me the details")],
        )
        assert intent.is_ready
        assert len(intent.data_types) == 2
        assert intent.suggestions[0].label == "Details"

    def test_not_ready_intent(self):
        intent = QueryIntent(
            is_ready=False,
            clarification_msg="What time period would you like to see?",
            confidence=0.3,
        )
        assert not intent.is_ready
        assert intent.clarification_msg

    def test_with_date_range(self):
        intent = QueryIntent(
            is_ready=True,
            data_types=[HealthDataType.MEAL],
            date_range=DateRange(start="2026-03-20T00:00:00Z", end="2026-03-24T00:00:00Z"),
        )
        assert intent.date_range.start.day == 20


class TestQueryResponse:
    def test_backward_compatible(self):
        resp = QueryResponse(
            is_ready=True,
            user_message="How were my sugars?",
            message="Your glucose averaged 145 mg/dL.",
            data_types=["cgm_range_stats"],
            trace_id="trc_123",
            cost_usd=0.005,
        )
        assert resp.type == "response"
        assert resp.trace_id == "trc_123"


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


def _make_mock_gateway():
    """Create a mock ModelGateway that returns a QueryIntent."""
    gateway = AsyncMock()

    intent = QueryIntent(
        is_ready=True,
        data_types=[HealthDataType.CGM_RANGE],
        confidence=0.9,
        suggestions=[SuggestedAction(label="More", description="Show more details")],
    )
    meta = LLMResponse(
        content="{}",
        model_id="gpt-4.1-mini",
        usage=LLMUsage(
            input_tokens=500,
            output_tokens=100,
            cost=CostBreakdown(total_cost=0.002),
        ),
        latency_ms=300,
        trace_id="trc_test",
    )
    gateway.extract = AsyncMock(return_value=(intent, meta))
    gateway.complete = AsyncMock(return_value=LLMResponse(
        content="Your glucose averaged 145 mg/dL this week, which is slightly above the typical target.",
        model_id="gpt-5.1",
        usage=LLMUsage(input_tokens=1000, output_tokens=200, cost=CostBreakdown(total_cost=0.01)),
        latency_ms=2000,
    ))
    return gateway


def _make_mock_retriever():
    """Create a mock CompositeRetriever."""
    retriever = AsyncMock()
    retriever.retrieve = AsyncMock(return_value=CompositeResult(
        items=[
            RetrievalResult(
                payload={"data_type": "cgm_range_stats", "average_glucose": 145, "tir": 0.62},
                source="mongo:cgm_reports",
                data_type="cgm_range_stats",
            ),
        ],
        executed_sources=["mongo:cgm_reports"],
    ))
    return retriever


def _make_mock_memory():
    """Create a mock MemoryStore."""
    memory = AsyncMock()
    memory.get_patient_facts = AsyncMock(return_value=[])
    memory.get_thread_turns = AsyncMock(return_value=[])
    memory.append_turn = AsyncMock()
    return memory


def _make_agent(**overrides):
    """Create a HealthQueryAgent with mocked dependencies."""
    prompts = PromptRegistry()
    prompts.register_directory(
        Path("lib/ai_foundation/agents/health_query/prompts"),
        namespace="health_query",
    )
    return HealthQueryAgent(
        gateway=overrides.get("gateway", _make_mock_gateway()),
        memory=overrides.get("memory", _make_mock_memory()),
        prompts=overrides.get("prompts", prompts),
        retriever=overrides.get("retriever", _make_mock_retriever()),
        tracer=overrides.get("tracer", None),
        event_bus=overrides.get("event_bus", None),
    )


def _make_input(message: str = "How were my sugars this week?", **kwargs) -> AgentInput:
    return AgentInput(
        message=message,
        context=AgentContext(
            patient_id=kwargs.get("patient_id", "p123"),
            user_id=kwargs.get("user_id", "u123"),
            user_role=kwargs.get("user_role", "patient"),
            thread_id=kwargs.get("thread_id", "t123"),
            patient_ids=kwargs.get("patient_ids", ["p123"]),
        ),
    )


class TestHealthQueryAgent:
    def test_agent_id(self):
        agent = _make_agent()
        assert agent.agent_id == "health_query_v3"

    @pytest.mark.asyncio
    async def test_run_ready_intent(self):
        agent = _make_agent()
        output = await agent.run(_make_input())

        assert output.is_ready is True
        assert "145" in output.message
        assert output.data.get("data_types") == ["cgm_range_stats"]
        assert len(output.suggestions) >= 1

    @pytest.mark.asyncio
    async def test_run_not_ready_intent(self):
        gateway = _make_mock_gateway()
        not_ready = QueryIntent(
            is_ready=False,
            clarification_msg="What time period?",
            confidence=0.3,
            suggestions=[SuggestedAction(label="Today", description="Show me today's data")],
        )
        gateway.extract = AsyncMock(return_value=(not_ready, LLMResponse(
            content="{}", model_id="gpt-4.1-mini",
            usage=LLMUsage(cost=CostBreakdown(total_cost=0.001)),
        )))

        agent = _make_agent(gateway=gateway)
        output = await agent.run(_make_input("how am I doing"))

        assert output.is_ready is False
        assert "time period" in output.message.lower()
        assert len(output.suggestions) >= 1
        # Gateway.complete should NOT have been called
        gateway.complete.assert_not_called()

    @pytest.mark.asyncio
    async def test_run_persists_turns(self):
        memory = _make_mock_memory()
        agent = _make_agent(memory=memory)
        await agent.run(_make_input())

        # Should persist both user and assistant turns
        assert memory.append_turn.call_count == 2
        calls = memory.append_turn.call_args_list
        assert calls[0][0][1].role == "user"
        assert calls[1][0][1].role == "assistant"

    @pytest.mark.asyncio
    async def test_run_with_no_memory(self):
        agent = _make_agent(memory=None)
        output = await agent.run(_make_input())
        assert output.is_ready is True  # should still work without memory

    @pytest.mark.asyncio
    async def test_run_with_no_retriever(self):
        agent = _make_agent(retriever=None)
        output = await agent.run(_make_input())
        assert output.is_ready is True  # should still work, just no data

    @pytest.mark.asyncio
    async def test_run_handles_gateway_error(self):
        gateway = _make_mock_gateway()
        gateway.extract = AsyncMock(side_effect=Exception("LLM down"))
        agent = _make_agent(gateway=gateway)

        output = await agent.run(_make_input())
        assert output.is_ready is False
        assert "trouble" in output.message.lower()

    @pytest.mark.asyncio
    async def test_run_care_provider_role(self):
        agent = _make_agent()
        input = _make_input(user_role="care_provider", patient_ids=["p1", "p2"])
        output = await agent.run(input)
        assert output.is_ready is True

    def test_to_query_response(self):
        agent = _make_agent()
        input = _make_input()
        output = AgentOutput(
            message="Your glucose was stable.",
            is_ready=True,
            suggestions=[{"label": "More", "description": "Show more"}],
            data={"data_types": ["cgm_range_stats"], "confidence": 0.9},
            trace_id="trc_123",
            cost_usd=0.005,
            latency_ms=2000,
        )
        resp = agent.to_query_response(input, output)
        assert isinstance(resp, QueryResponse)
        assert resp.is_ready is True
        assert resp.trace_id == "trc_123"
        assert resp.final_response == "Your glucose was stable."

    def test_to_query_response_clarification(self):
        agent = _make_agent()
        input = _make_input()
        output = AgentOutput(
            message="What time period?",
            is_ready=False,
            data={"data_types": [], "confidence": 0.3},
        )
        resp = agent.to_query_response(input, output)
        assert resp.is_ready is False
        assert resp.clarification_msg == "What time period?"
        assert resp.final_response is None


class TestHealthQueryAgentStreaming:
    @pytest.mark.asyncio
    async def test_stream_ready_intent(self):
        gateway = _make_mock_gateway()

        # Mock the stream method to yield chunks
        async def mock_stream(**kwargs):
            yield MagicMock(delta="Your glucose ", finished=False)
            yield MagicMock(delta="was 145.", finished=False)
            yield MagicMock(delta="", finished=True, full_content="Your glucose was 145.", usage=None)

        gateway.stream = mock_stream

        agent = _make_agent(gateway=gateway)
        events = []
        async for event in agent.run_stream(_make_input()):
            events.append(event)

        # Parse event types
        event_types = []
        for e in events:
            if "event:" in e:
                event_type = e.split("event: ")[1].split("\n")[0]
                event_types.append(event_type)

        assert "status" in event_types
        assert "intent" in event_types
        assert "token" in event_types
        assert "done" in event_types

    @pytest.mark.asyncio
    async def test_stream_not_ready(self):
        gateway = _make_mock_gateway()
        gateway.extract = AsyncMock(return_value=(
            QueryIntent(is_ready=False, clarification_msg="What period?", confidence=0.2),
            LLMResponse(content="{}", model_id="m", usage=LLMUsage(cost=CostBreakdown())),
        ))

        agent = _make_agent(gateway=gateway)
        events = []
        async for event in agent.run_stream(_make_input()):
            events.append(event)

        # Should have token with clarification and done, but NO fetching_data status
        all_text = "".join(events)
        assert "What period?" in all_text
        assert "fetching_data" not in all_text

    @pytest.mark.asyncio
    async def test_stream_error_yields_error_event(self):
        gateway = _make_mock_gateway()
        gateway.extract = AsyncMock(side_effect=Exception("boom"))

        agent = _make_agent(gateway=gateway)
        events = []
        async for event in agent.run_stream(_make_input()):
            events.append(event)

        all_text = "".join(events)
        assert "event: error" in all_text


class TestPromptLoading:
    def test_prompts_directory_exists(self):
        prompts_dir = Path("lib/ai_foundation/agents/health_query/prompts")
        assert prompts_dir.exists()
        md_files = list(prompts_dir.glob("*.md"))
        assert len(md_files) >= 4  # system_patient, system_care_provider, intent, response

    def test_prompts_load_into_registry(self):
        registry = PromptRegistry()
        count = registry.register_directory(
            Path("lib/ai_foundation/agents/health_query/prompts"),
            namespace="health_query",
        )
        assert count >= 4
        assert "hq_system_patient" in registry
        assert "hq_system_care_provider" in registry
        assert "hq_intent_extraction" in registry
        assert "hq_response_generation" in registry

    def test_system_prompt_renders(self):
        registry = PromptRegistry()
        registry.register_directory(
            Path("lib/ai_foundation/agents/health_query/prompts"),
            namespace="health_query",
        )
        template = registry.get("hq_system_patient")
        rendered = template.render(current_time="2026-03-24 10:00 UTC")
        assert "2026-03-24" in rendered
        assert "patient" in rendered.lower()
