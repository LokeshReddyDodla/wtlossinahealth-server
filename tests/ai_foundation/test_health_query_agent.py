"""Tests for the Health Query Agent with agentic reasoning."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from lib.ai_foundation.agents.health_query.agent import HealthQueryAgent
from lib.ai_foundation.agents.health_query.contracts import (
    HealthDataType, QueryIntent, QueryResponse, SuggestedAction, DateRange,
)
from lib.ai_foundation.agents.health_query.context_loader import ContextLoader, AgentContext
from lib.ai_foundation.agents.health_query.persistence_service import PersistenceService
from lib.ai_foundation.agents.health_query.fact_extractor import FactExtractor
from lib.ai_foundation.agents.health_query.reasoning_engine import (
    ReasoningEngine, ReasoningResult, ReasoningTier,
)
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


def _mock_reasoning_engine():
    engine = AsyncMock(spec=ReasoningEngine)
    engine.reason = AsyncMock(return_value=ReasoningResult(
        response="Your glucose averaged 145 mg/dL this week.",
        steps=[],
        rounds_used=2,
        tools_called=1,
        total_cost=0.005,
        thinker_model="gpt-4.1-mini",
        responder_model="gpt-5.1",
        tier="standard",
    ))
    return engine


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
        reasoning_engine=overrides.get("reasoning_engine", _mock_reasoning_engine()),
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
    async def test_run_uses_reasoning_engine(self):
        engine = _mock_reasoning_engine()
        agent = _make_agent(reasoning_engine=engine)
        output = await agent.run(_make_input())
        engine.reason.assert_called_once()
        assert output.data.get("rounds_used") == 2
        assert output.data.get("tier") == "standard"

    @pytest.mark.asyncio
    async def test_run_not_ready(self):
        gw = _mock_gateway()
        gw.extract = AsyncMock(return_value=(
            QueryIntent(is_ready=False, clarification_msg="What time?", confidence=0.3,
                        suggestions=[SuggestedAction(label="Today", description="Show today")]),
            LLMResponse(content="{}", model_id="m", usage=LLMUsage(cost=CostBreakdown(total_cost=0.001))),
        ))
        engine = _mock_reasoning_engine()
        agent = _make_agent(gateway=gw, reasoning_engine=engine)
        output = await agent.run(_make_input("how am I"))
        assert not output.is_ready
        assert "time" in output.message.lower()
        # Reasoning engine should NOT have been called
        engine.reason.assert_not_called()

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
        """Agent works even with minimal services (graceful degradation)."""
        engine = _mock_reasoning_engine()
        agent = HealthQueryAgent(gateway=_mock_gateway(), prompts=PromptRegistry(), reasoning_engine=engine)
        agent.prompts.register_directory(Path("lib/ai_foundation/agents/health_query/prompts"), namespace="health_query")
        output = await agent.run(_make_input())
        assert output.is_ready

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
        engine = _mock_reasoning_engine()

        async def mock_reason_stream(**kwargs):
            from lib.ai_foundation.streaming.sse import sse_status, sse_token, sse_reasoning, sse_done, SSEDonePayload, PipelineStage
            yield sse_status(PipelineStage.ANALYZING, "Investigating...")
            yield sse_reasoning(1, "Let me check glucose data")
            yield sse_token("Hello ")
            yield sse_token("world.")
            yield sse_done(SSEDonePayload(cost_usd=0.005, data={"rounds_used": 1}))

        engine.reason_stream = mock_reason_stream
        agent = _make_agent(reasoning_engine=engine)
        events = []
        async for e in agent.run_stream(_make_input()):
            events.append(e)

        all_text = "".join(events)
        assert "intent" in all_text or "status" in all_text
        assert "token" in all_text
        assert "done" in all_text

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
        assert "analyzing" not in all_text

    @pytest.mark.asyncio
    async def test_stream_error(self):
        gw = _mock_gateway()
        gw.extract = AsyncMock(side_effect=Exception("boom"))
        agent = _make_agent(gateway=gw)
        events = []
        async for e in agent.run_stream(_make_input()):
            events.append(e)
        assert any("error" in e for e in events)


class TestReasoningEngine:
    def test_tier_configs(self):
        from lib.ai_foundation.agents.health_query.reasoning_engine import TIER_CONFIGS
        assert TIER_CONFIGS[ReasoningTier.BASIC].max_tool_calls == 2
        assert TIER_CONFIGS[ReasoningTier.STANDARD].max_tool_calls == 5
        assert TIER_CONFIGS[ReasoningTier.ADVANCED].max_tool_calls == 10
        assert TIER_CONFIGS[ReasoningTier.UNLIMITED].max_tool_calls == 20

    def test_reasoning_result(self):
        result = ReasoningResult(
            response="Test", rounds_used=3, tools_called=5,
            total_cost=0.01, tier="standard",
        )
        assert result.rounds_used == 3
        assert result.tools_called == 5


class TestFactExtractor:
    def test_extractor_exists(self):
        """FactExtractor now always runs LLM — no keyword heuristic to test."""
        from lib.ai_foundation.agents.health_query.fact_extractor import FactExtractor
        ext = FactExtractor()
        assert hasattr(ext, "extract_if_needed")


class TestPlanner:
    def test_plan_models(self):
        from lib.ai_foundation.agents.health_query.planner import InvestigationPlan, PlanStep
        plan = InvestigationPlan(
            strategy="Check glucose then meals",
            steps=[
                PlanStep(tool_name="look_up", arguments={"data_types": ["cgm_range_stats"]}, reason="Get glucose", phase=1),
                PlanStep(tool_name="look_up", arguments={"data_types": ["meal"]}, reason="Get meals", phase=1),
                PlanStep(tool_name="investigate_day", arguments={"date": "2026-03-18"}, reason="Check spike day", phase=2),
            ],
            domains_involved=["glucose", "nutrition"],
        )
        assert len(plan.steps) == 3
        assert len([s for s in plan.steps if s.phase == 1]) == 2


class TestReflector:
    def test_reflection_models(self):
        from lib.ai_foundation.agents.health_query.reflector import ReflectionResult
        result = ReflectionResult(
            is_complete=True, confidence=0.85,
            gaps=[], safety_concerns=["Low glucose at 3am on March 20"],
        )
        assert result.is_complete
        assert result.confidence == 0.85
        assert len(result.safety_concerns) == 1

    def test_reflection_with_gaps(self):
        from lib.ai_foundation.agents.health_query.reflector import ReflectionResult
        result = ReflectionResult(
            is_complete=False, confidence=0.5,
            gaps=["Missing meal data for spike day", "No baseline comparison"],
        )
        assert not result.is_complete
        assert len(result.gaps) == 2


class TestSpecialists:
    def test_domain_specs(self):
        from lib.ai_foundation.agents.health_query.specialists import (
            GLUCOSE_SPEC, NUTRITION_SPEC, FITNESS_SPEC, VITALS_SPEC, SLEEP_SPEC, DOCUMENTS_SPEC, DEFAULT_SPECS,
        )
        assert GLUCOSE_SPEC.domain == "glucose"
        assert "cgm_range_stats" in GLUCOSE_SPEC.data_types
        assert NUTRITION_SPEC.domain == "nutrition"
        assert "meal" in NUTRITION_SPEC.data_types
        assert FITNESS_SPEC.domain == "fitness"
        assert "fitness_overview" in FITNESS_SPEC.data_types
        assert VITALS_SPEC.domain == "vitals"
        assert "vital" in VITALS_SPEC.data_types
        assert SLEEP_SPEC.domain == "sleep"
        assert "sleep" in SLEEP_SPEC.data_types
        assert DOCUMENTS_SPEC.domain == "documents"
        assert "patient_document" in DOCUMENTS_SPEC.data_types
        assert len(DEFAULT_SPECS) == 6

    def test_specialist_findings(self):
        from lib.ai_foundation.agents.health_query.specialists import SpecialistFindings
        findings = SpecialistFindings(
            domain="glucose", findings="3 spikes found",
            tool_calls_used=2, cost=0.003,
        )
        assert findings.domain == "glucose"
        assert findings.tool_calls_used == 2


class TestDomainMapping:
    def test_resolve_specialist_domains(self):
        from lib.ai_foundation.agents.health_query.contracts import resolve_specialist_domains
        domains = resolve_specialist_domains([HealthDataType.CGM_RANGE, HealthDataType.MEAL])
        assert "glucose" in domains
        assert "nutrition" in domains
        assert len(domains) == 2

    def test_resolve_single_domain(self):
        from lib.ai_foundation.agents.health_query.contracts import resolve_specialist_domains
        domains = resolve_specialist_domains([HealthDataType.MEAL])
        assert domains == ["nutrition"]

    def test_resolve_domains(self):
        from lib.ai_foundation.agents.health_query.contracts import resolve_domains, DomainName
        domains = resolve_domains([HealthDataType.CGM_RANGE, HealthDataType.FITNESS_OVERVIEW])
        assert DomainName.CGM in domains
        assert DomainName.FITNESS in domains


class TestPromptLoading:
    def test_prompts_load(self):
        registry = PromptRegistry()
        count = registry.register_directory(Path("lib/ai_foundation/agents/health_query/prompts"), namespace="hq")
        assert count >= 8  # system_patient, system_admin, system_care_provider, intent, reasoning, final_response, planning, reflection
        assert "hq_system_patient" in registry
        assert "hq_system_admin" in registry
        assert "hq_reasoning" in registry
        assert "hq_final_response" in registry
        assert "hq_planning" in registry
        assert "hq_reflection" in registry

    def test_system_prompt_renders(self):
        registry = PromptRegistry()
        registry.register_directory(Path("lib/ai_foundation/agents/health_query/prompts"), namespace="hq")
        template = registry.get("hq_system_patient")
        rendered = template.render(current_time="2026-03-24 10:00 UTC")
        assert "2026-03-24" in rendered


class TestSSEEvents:
    def test_reasoning_event(self):
        from lib.ai_foundation.streaming.sse import sse_reasoning
        event = sse_reasoning(1, "Looking at glucose data")
        assert "event: reasoning" in event
        assert "Looking at glucose data" in event

    def test_tool_call_event(self):
        from lib.ai_foundation.streaming.sse import sse_tool_call
        event = sse_tool_call("look_up", {"data_types": ["meal"]})
        assert "event: tool_call" in event
        assert "look_up" in event

    def test_tool_result_event(self):
        from lib.ai_foundation.streaming.sse import sse_tool_result
        event = sse_tool_result("look_up", "3 meals found")
        assert "event: tool_result" in event
        assert "3 meals found" in event

    def test_plan_event(self):
        from lib.ai_foundation.streaming.sse import sse_plan
        event = sse_plan("Check glucose then meals", 4, ["glucose", "nutrition"])
        assert "event: plan" in event
        assert "glucose" in event

    def test_reflection_event(self):
        from lib.ai_foundation.streaming.sse import sse_reflection
        event = sse_reflection(0.85, [], True)
        assert "event: reflection" in event
        assert "0.85" in event

    def test_specialist_events(self):
        from lib.ai_foundation.streaming.sse import sse_specialist_start, sse_specialist_done
        start = sse_specialist_start("glucose", 3)
        assert "event: specialist_start" in start
        assert "glucose" in start
        done = sse_specialist_done("glucose", "Found 3 spike patterns")
        assert "event: specialist_done" in done
        assert "spike" in done
