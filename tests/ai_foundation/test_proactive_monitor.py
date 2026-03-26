"""Tests for the Proactive Monitor Agent."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from lib.ai_foundation.agents.proactive_monitor.agent import ProactiveMonitorAgent, _InsightList
from lib.ai_foundation.agents.proactive_monitor.contracts import (
    BatchScanResult,
    HealthInsight,
    InsightCategory,
    InsightSeverity,
    ScanResult,
)
from lib.ai_foundation.agents.state import AgentContext, AgentInput
from lib.ai_foundation.models.gateway import LLMResponse, LLMUsage
from lib.ai_foundation.models.pricing import CostBreakdown
from lib.ai_foundation.prompts.registry import PromptRegistry
from lib.ai_foundation.retrieval.base import CompositeResult, RetrievalResult


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


# ---------------------------------------------------------------------------
# Agent helpers
# ---------------------------------------------------------------------------


def _make_gateway_with_insights(insights: list[HealthInsight] | None = None):
    """Mock gateway that returns insight analysis."""
    gateway = AsyncMock()
    insight_list = _InsightList(insights=insights if insights is not None else [
        HealthInsight(
            category=InsightCategory.GLUCOSE_SPIKE,
            severity=InsightSeverity.ATTENTION,
            title="Recurring glucose spikes",
            body="You've had 3 post-meal spikes today. Consider adding protein to your meals.",
            patient_id="",
            suggested_query="Show me my glucose spikes today",
        ),
        HealthInsight(
            category=InsightCategory.FITNESS_STREAK,
            severity=InsightSeverity.INFO,
            title="5-day activity streak!",
            body="Great job — you've been consistently active for 5 days!",
            patient_id="",
            actionable=False,
        ),
    ])
    meta = LLMResponse(
        content="{}", model_id="gpt-4.1-mini",
        usage=LLMUsage(input_tokens=300, output_tokens=100, cost=CostBreakdown(total_cost=0.001)),
    )
    gateway.extract = AsyncMock(return_value=(insight_list, meta))
    return gateway


def _make_retriever(items=None):
    retriever = AsyncMock()
    retriever.retrieve = AsyncMock(return_value=CompositeResult(
        items=items or [
            RetrievalResult(payload={"data_type": "cgm_range_stats", "average_glucose": 165}, source="mongo"),
            RetrievalResult(payload={"data_type": "meal", "calories": 500, "meal_type": "lunch"}, source="mongo"),
            RetrievalResult(payload={"data_type": "fitness_overview", "steps": 8500}, source="mongo"),
        ],
        executed_sources=["mongo"],
    ))
    return retriever


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
        gateway=overrides.get("gateway", _make_gateway_with_insights()),
        memory=overrides.get("memory", _make_memory()),
        prompts=overrides.get("prompts", prompts),
        retriever=overrides.get("retriever", _make_retriever()),
        event_bus=overrides.get("event_bus", _make_event_bus()),
    )


# ---------------------------------------------------------------------------
# Agent tests
# ---------------------------------------------------------------------------


class TestProactiveMonitorAgent:
    def test_agent_id(self):
        agent = _make_agent()
        assert agent.agent_id == "proactive_monitor"

    @pytest.mark.asyncio
    async def test_scan_patient_with_insights(self):
        agent = _make_agent()
        result = await agent.scan_patient("p123")

        assert result.patient_id == "p123"
        assert result.has_insights is True
        assert len(result.insights) == 2
        assert result.insights[0].patient_id == "p123"  # stamped
        assert result.scan_duration_ms >= 0
        assert result.error is None

    @pytest.mark.asyncio
    async def test_scan_patient_no_data(self):
        retriever = AsyncMock()
        retriever.retrieve = AsyncMock(return_value=CompositeResult(items=[]))

        agent = _make_agent(retriever=retriever)
        result = await agent.scan_patient("p_empty")

        assert result.data_available is False
        assert not result.has_insights

    @pytest.mark.asyncio
    async def test_scan_patient_no_insights(self):
        gateway = _make_gateway_with_insights(insights=[])
        agent = _make_agent(gateway=gateway, retriever=_make_retriever())
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
    async def test_scan_handles_error(self):
        gateway = AsyncMock()
        gateway.extract = AsyncMock(side_effect=Exception("LLM down"))

        agent = _make_agent(gateway=gateway)
        result = await agent.scan_patient("p_error")

        assert result.error is not None
        assert "LLM down" in result.error
        assert not result.has_insights

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
    async def test_scan_batch_mixed(self):
        """Batch with mix of success and no-data patients."""
        call_count = 0

        async def mock_retrieve(request):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                return CompositeResult(items=[])  # second patient has no data
            return CompositeResult(items=[
                RetrievalResult(payload={"data_type": "meal", "calories": 400}, source="mongo"),
            ], executed_sources=["mongo"])

        retriever = AsyncMock()
        retriever.retrieve = mock_retrieve

        agent = _make_agent(retriever=retriever)
        batch = await agent.scan_batch(["p1", "p2", "p3"])

        assert batch.scanned == 3
        # p2 has no data so no insights
        no_data = [r for r in batch.results if not r.data_available]
        assert len(no_data) == 1

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
    async def test_no_retriever_returns_no_data(self):
        agent = _make_agent(retriever=None)
        result = await agent.scan_patient("p1")
        assert not result.data_available

    @pytest.mark.asyncio
    async def test_no_event_bus_still_works(self):
        agent = _make_agent(event_bus=None)
        result = await agent.scan_patient("p1")
        assert result.has_insights  # insights detected even without bus


class TestPromptLoading:
    def test_prompts_directory_exists(self):
        assert Path("lib/ai_foundation/agents/proactive_monitor/prompts").exists()

    def test_scan_prompt_loads(self):
        registry = PromptRegistry()
        count = registry.register_directory(
            Path("lib/ai_foundation/agents/proactive_monitor/prompts"),
            namespace="proactive_monitor",
        )
        assert count >= 1
        assert "pm_scan_analysis" in registry
        prompt = registry.get("pm_scan_analysis")
        assert "noteworthy" in prompt.body.lower()
