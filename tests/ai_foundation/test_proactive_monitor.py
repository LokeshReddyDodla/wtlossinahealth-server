"""Tests for the Proactive Monitor Agent (v2 — ReasoningEngine-powered)."""

from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from lib.ai_foundation.agents.proactive_monitor.agent import ProactiveMonitorAgent
from lib.ai_foundation.agents.proactive_monitor.contracts import (
    BatchScanResult,
    HealthInsight,
    InsightCategory,
    InsightSeverity,
    ScanInsights,
    ScanResult,
)
from lib.ai_foundation.agents.state import AgentContext, AgentInput
from lib.ai_foundation.models.gateway import LLMResponse, LLMUsage
from lib.ai_foundation.models.pricing import CostBreakdown
from lib.ai_foundation.prompts.registry import PromptRegistry


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------


class TestContracts:
    def test_health_insight_defaults(self):
        i = HealthInsight(
            category=InsightCategory.GLUCOSE_SPIKE,
            severity=InsightSeverity.ATTENTION,
            title="Glucose spike detected",
            body="You had 3 spikes today after meals.",
            patient_id="p123",
        )
        assert i.insight_id.startswith("ins_")
        assert i.actionable is True

    def test_health_insight_default_patient_id(self):
        """HealthInsight.patient_id defaults to empty string for extraction."""
        i = HealthInsight(
            category=InsightCategory.GENERAL,
            severity=InsightSeverity.INFO,
            title="Test",
            body="Test body",
        )
        assert i.patient_id == ""

    def test_scan_result_properties(self):
        r = ScanResult(
            patient_id="p1",
            insights=[
                HealthInsight(category=InsightCategory.GLUCOSE_SPIKE, severity=InsightSeverity.WARNING, title="t", body="b", patient_id="p1"),
                HealthInsight(category=InsightCategory.FITNESS_STREAK, severity=InsightSeverity.INFO, title="t", body="b", patient_id="p1"),
            ],
        )
        assert r.has_insights is True
        assert r.alert_count == 1  # only WARNING counts

    def test_scan_result_no_insights(self):
        r = ScanResult(patient_id="p1")
        assert r.has_insights is False
        assert r.alert_count == 0

    def test_batch_scan_result(self):
        b = BatchScanResult(total_patients=3, scanned=3, with_insights=1, total_insights=2)
        assert b.errors == 0

    def test_scan_insights_model(self):
        """ScanInsights extraction model works for structured extraction."""
        si = ScanInsights(insights=[
            HealthInsight(
                category=InsightCategory.GLUCOSE_SPIKE,
                severity=InsightSeverity.ATTENTION,
                title="Test",
                body="Test body",
            ),
        ])
        assert len(si.insights) == 1

    def test_scan_insights_empty(self):
        si = ScanInsights()
        assert si.insights == []


# ---------------------------------------------------------------------------
# Agent helpers
# ---------------------------------------------------------------------------


@dataclass
class _FakeReasoningResult:
    """Mimics ReasoningResult from the reasoning engine."""
    response: str = "Patient shows 3 glucose spikes above 200 in the last 48 hours."
    steps: list = field(default_factory=list)
    rounds_used: int = 1
    tools_called: int = 1
    total_cost: float = 0.002
    thinker_model: str = "gpt-4.1-mini"
    responder_model: str = "gpt-4.1-mini"
    tier: str = "basic"


def _make_default_insights() -> list[HealthInsight]:
    return [
        HealthInsight(
            category=InsightCategory.GLUCOSE_SPIKE,
            severity=InsightSeverity.ATTENTION,
            title="Recurring glucose spikes",
            body="You've had 3 post-meal spikes today. Consider adding protein to your meals.",
            suggested_query="Show me my glucose spikes today",
        ),
        HealthInsight(
            category=InsightCategory.FITNESS_STREAK,
            severity=InsightSeverity.INFO,
            title="5-day activity streak!",
            body="Great job — you've been consistently active for 5 days!",
            actionable=False,
        ),
    ]


def _make_reasoning_engine(response_text: str | None = None):
    """Mock ReasoningEngine that returns a fake result."""
    engine = AsyncMock()
    result = _FakeReasoningResult(
        response=response_text or "Patient shows 3 glucose spikes above 200 in the last 48 hours.",
    )
    engine.reason = AsyncMock(return_value=result)
    return engine


def _make_gateway_with_extraction(insights: list[HealthInsight] | None = None):
    """Mock gateway that returns structured insight extraction."""
    gateway = AsyncMock()
    scan_insights = ScanInsights(insights=insights if insights is not None else _make_default_insights())
    meta = LLMResponse(
        content="{}", model_id="gpt-4.1-mini",
        usage=LLMUsage(input_tokens=300, output_tokens=100, cost=CostBreakdown(total_cost=0.001)),
    )
    gateway.extract = AsyncMock(return_value=(scan_insights, meta))
    return gateway


def _make_tool_executor():
    return AsyncMock()


def _make_memory():
    memory = AsyncMock()
    memory.get_patient_facts = AsyncMock(return_value=[])
    return memory


def _make_event_bus():
    bus = AsyncMock()
    bus.publish = AsyncMock()
    return bus


def _make_agent(**overrides):
    prompts = PromptRegistry()
    prompts.register_directory(
        Path("lib/ai_foundation/agents/proactive_monitor/prompts"),
        namespace="proactive_monitor",
    )
    return ProactiveMonitorAgent(
        gateway=overrides.get("gateway", _make_gateway_with_extraction()),
        reasoning_engine=overrides.get("reasoning_engine", _make_reasoning_engine()),
        tool_executor=overrides.get("tool_executor", _make_tool_executor()),
        memory=overrides.get("memory", _make_memory()),
        prompts=overrides.get("prompts", prompts),
        event_bus=overrides.get("event_bus", _make_event_bus()),
    )


# ---------------------------------------------------------------------------
# Agent tests
# ---------------------------------------------------------------------------


class TestProactiveMonitorAgent:
    def test_agent_id(self):
        agent = _make_agent()
        assert agent.agent_id == "proactive_monitor_v2"

    @pytest.mark.asyncio
    async def test_scan_patient_with_insights(self):
        agent = _make_agent()
        result = await agent.scan_patient("p123", "Sarah")

        assert result.patient_id == "p123"
        assert result.has_insights is True
        assert len(result.insights) == 2
        assert result.insights[0].patient_id == "p123"  # stamped
        assert result.scan_duration_ms >= 0
        assert result.error is None

    @pytest.mark.asyncio
    async def test_scan_patient_without_name(self):
        agent = _make_agent()
        result = await agent.scan_patient("p123")

        assert result.patient_id == "p123"
        assert result.has_insights is True

    @pytest.mark.asyncio
    async def test_scan_calls_reasoning_engine(self):
        engine = _make_reasoning_engine()
        agent = _make_agent(reasoning_engine=engine)
        await agent.scan_patient("p123", "Sarah")

        engine.reason.assert_called_once()
        call_kwargs = engine.reason.call_args.kwargs
        assert call_kwargs["patient_ids"] == ["p123"]
        assert call_kwargs["patient_names"] == {"p123": "Sarah"}
        assert "cgm_range_stats" in call_kwargs["intent_data_types"]

    @pytest.mark.asyncio
    async def test_scan_patient_no_insights(self):
        gateway = _make_gateway_with_extraction(insights=[])
        agent = _make_agent(gateway=gateway)
        result = await agent.scan_patient("p_healthy")

        assert result.data_available is True
        assert not result.has_insights
        assert result.error is None

    @pytest.mark.asyncio
    async def test_scan_publishes_events(self):
        event_bus = _make_event_bus()
        agent = _make_agent(event_bus=event_bus)
        await agent.scan_patient("p123")

        assert event_bus.publish.call_count == 2  # 2 insights
        published_event = event_bus.publish.call_args_list[0][0][0]
        assert published_event.event_type == "proactive_insight"
        assert published_event.patient_id == "p123"
        assert published_event.data["category"] == "glucose_spike"

    @pytest.mark.asyncio
    async def test_scan_handles_reasoning_error(self):
        engine = AsyncMock()
        engine.reason = AsyncMock(side_effect=Exception("LLM down"))

        agent = _make_agent(reasoning_engine=engine)
        result = await agent.scan_patient("p_error")

        assert result.error is not None
        assert "LLM down" in result.error
        assert not result.has_insights

    @pytest.mark.asyncio
    async def test_scan_handles_extraction_error(self):
        """If insight extraction fails, return empty insights (no crash)."""
        gateway = AsyncMock()
        gateway.extract = AsyncMock(side_effect=Exception("Extraction failed"))

        agent = _make_agent(gateway=gateway)
        result = await agent.scan_patient("p_extract_fail")

        assert result.error is None  # reasoning succeeded
        assert not result.has_insights  # extraction failed gracefully

    @pytest.mark.asyncio
    async def test_scan_batch(self):
        agent = _make_agent()
        batch = await agent.scan_batch(["p1", "p2", "p3"])

        assert batch.total_patients == 3
        assert batch.scanned == 3
        assert batch.with_insights == 3
        assert batch.total_insights == 6  # 2 per patient
        assert batch.duration_ms >= 0

    @pytest.mark.asyncio
    async def test_scan_batch_with_names(self):
        engine = _make_reasoning_engine()
        agent = _make_agent(reasoning_engine=engine)
        await agent.scan_batch(
            ["p1", "p2"],
            patient_names={"p1": "Alice", "p2": "Bob"},
        )

        assert engine.reason.call_count == 2
        # Verify names were passed
        first_call = engine.reason.call_args_list[0].kwargs
        assert first_call["patient_names"] == {"p1": "Alice"}
        second_call = engine.reason.call_args_list[1].kwargs
        assert second_call["patient_names"] == {"p2": "Bob"}

    @pytest.mark.asyncio
    async def test_scan_batch_with_error(self):
        """Batch continues even if one patient's reasoning fails."""
        call_count = 0

        async def mock_reason(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise Exception("LLM timeout")
            return _FakeReasoningResult()

        engine = AsyncMock()
        engine.reason = mock_reason

        agent = _make_agent(reasoning_engine=engine)
        batch = await agent.scan_batch(["p1", "p2", "p3"])

        assert batch.scanned == 3
        # p2 had an error
        errored = [r for r in batch.results if r.error]
        assert len(errored) == 1
        assert batch.errors == 1

    @pytest.mark.asyncio
    async def test_run_interface(self):
        """Test the BaseAgent.run() interface."""
        agent = _make_agent()
        input = AgentInput(
            message="scan",
            context=AgentContext(patient_id="p123"),
        )
        output = await agent.run(input)
        assert output.is_ready is True
        assert "spike" in output.message.lower() or "streak" in output.message.lower()
        assert output.data.get("insights")

    @pytest.mark.asyncio
    async def test_run_no_patient_id(self):
        agent = _make_agent()
        input = AgentInput(message="scan", context=AgentContext())
        output = await agent.run(input)
        assert output.is_ready is False

    @pytest.mark.asyncio
    async def test_run_no_insights(self):
        gateway = _make_gateway_with_extraction(insights=[])
        agent = _make_agent(gateway=gateway)
        input = AgentInput(
            message="scan",
            context=AgentContext(patient_id="p_healthy"),
        )
        output = await agent.run(input)
        assert output.is_ready is True
        assert "no noteworthy" in output.message.lower()

    @pytest.mark.asyncio
    async def test_no_event_bus_still_works(self):
        agent = _make_agent(event_bus=None)
        result = await agent.scan_patient("p1")
        assert result.has_insights  # insights detected even without bus

    @pytest.mark.asyncio
    async def test_no_memory_still_works(self):
        agent = _make_agent(memory=None)
        result = await agent.scan_patient("p1")
        assert result.has_insights

    @pytest.mark.asyncio
    async def test_memory_error_handled_gracefully(self):
        memory = AsyncMock()
        memory.get_patient_facts = AsyncMock(side_effect=Exception("DB down"))
        agent = _make_agent(memory=memory)
        result = await agent.scan_patient("p1")
        # Should still work — memory error is swallowed
        assert result.error is None

    @pytest.mark.asyncio
    async def test_patient_id_stamped_on_insights(self):
        """Verify patient_id is stamped on all extracted insights."""
        agent = _make_agent()
        result = await agent.scan_patient("p999")
        for insight in result.insights:
            assert insight.patient_id == "p999"


class TestPromptLoading:
    def test_prompts_directory_exists(self):
        assert Path("lib/ai_foundation/agents/proactive_monitor/prompts").exists()

    def test_scan_prompts_load(self):
        registry = PromptRegistry()
        count = registry.register_directory(
            Path("lib/ai_foundation/agents/proactive_monitor/prompts"),
            namespace="proactive_monitor",
        )
        assert count >= 3  # scan_system, scan_reasoning, scan_response (+ scan_analysis)

    def test_system_prompt_loads(self):
        registry = PromptRegistry()
        registry.register_directory(
            Path("lib/ai_foundation/agents/proactive_monitor/prompts"),
            namespace="proactive_monitor",
        )
        assert "pm_scan_system" in registry
        prompt = registry.get("pm_scan_system")
        assert "health monitor" in prompt.body.lower()

    def test_system_prompt_renders_time(self):
        registry = PromptRegistry()
        registry.register_directory(
            Path("lib/ai_foundation/agents/proactive_monitor/prompts"),
            namespace="proactive_monitor",
        )
        prompt = registry.get("pm_scan_system")
        rendered = prompt.render(current_time="2026-01-01 12:00 UTC")
        assert "2026-01-01 12:00 UTC" in rendered

    def test_reasoning_prompt_loads(self):
        registry = PromptRegistry()
        registry.register_directory(
            Path("lib/ai_foundation/agents/proactive_monitor/prompts"),
            namespace="proactive_monitor",
        )
        assert "pm_scan_reasoning" in registry
        prompt = registry.get("pm_scan_reasoning")
        assert "glucose" in prompt.body.lower()

    def test_response_prompt_loads(self):
        registry = PromptRegistry()
        registry.register_directory(
            Path("lib/ai_foundation/agents/proactive_monitor/prompts"),
            namespace="proactive_monitor",
        )
        assert "pm_scan_response" in registry
        prompt = registry.get("pm_scan_response")
        assert "noteworthy" in prompt.body.lower()

    def test_legacy_analysis_prompt_still_exists(self):
        """The old scan_analysis.md is still present (backward compat)."""
        registry = PromptRegistry()
        registry.register_directory(
            Path("lib/ai_foundation/agents/proactive_monitor/prompts"),
            namespace="proactive_monitor",
        )
        assert "pm_scan_analysis" in registry
