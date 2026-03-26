"""Tests for the Proactive Monitor Agent (v2 — ReasoningEngine-powered)."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

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
from lib.ai_foundation.agents.proactive_monitor.insight_tracker import (
    InsightTracker,
    COLLECTION_NAME,
    _DEDUP_HOURS,
    _CONSECUTIVE_TOLERANCE_HOURS,
    _ESCALATE_ATTENTION_DAYS,
    _ESCALATE_WARNING_DAYS,
    _TTL_SECONDS,
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


def _make_insight_tracker(*, should_send_result=(True, "info")):
    """Create a mock InsightTracker.

    By default allows all insights through as 'info' severity.
    """
    tracker = AsyncMock(spec=InsightTracker)
    tracker.should_send = AsyncMock(return_value=should_send_result)
    tracker.record = AsyncMock()
    tracker.ensure_indexes = AsyncMock()
    return tracker


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
        insight_tracker=overrides.get("insight_tracker", None),
    )


# ---------------------------------------------------------------------------
# InsightTracker — mock MongoDB collection
# ---------------------------------------------------------------------------


def _make_mock_mongo_store():
    """Create a mock MongoStore with a mock collection."""
    store = MagicMock()
    collection = AsyncMock()
    collection.find_one = AsyncMock(return_value=None)
    collection.insert_one = AsyncMock()
    collection.create_index = AsyncMock()
    store.get_collection = MagicMock(return_value=collection)
    return store, collection


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


# ---------------------------------------------------------------------------
# Dedup + Escalation Integration Tests
# ---------------------------------------------------------------------------


class TestDedupEscalationIntegration:
    """Test dedup + escalation integration in the agent scan pipeline."""

    @pytest.mark.asyncio
    async def test_no_tracker_passes_all_insights(self):
        """Without an InsightTracker, all insights pass through unfiltered."""
        agent = _make_agent(insight_tracker=None)
        result = await agent.scan_patient("p1")
        assert len(result.insights) == 2

    @pytest.mark.asyncio
    async def test_tracker_allows_first_time_insights(self):
        """InsightTracker allows first-time insights through."""
        tracker = _make_insight_tracker(should_send_result=(True, "info"))
        agent = _make_agent(insight_tracker=tracker)
        result = await agent.scan_patient("p1")

        assert len(result.insights) == 2
        # Should have called should_send + record for each insight
        assert tracker.should_send.call_count == 2
        assert tracker.record.call_count == 2

    @pytest.mark.asyncio
    async def test_tracker_blocks_duplicate_insights(self):
        """InsightTracker blocks insights sent within 24h."""
        tracker = _make_insight_tracker(should_send_result=(False, "info"))
        agent = _make_agent(insight_tracker=tracker)
        result = await agent.scan_patient("p1")

        assert len(result.insights) == 0
        # should_send called but record NOT called (blocked)
        assert tracker.should_send.call_count == 2
        assert tracker.record.call_count == 0

    @pytest.mark.asyncio
    async def test_tracker_escalates_severity(self):
        """InsightTracker escalates severity for persistent patterns."""
        tracker = _make_insight_tracker(should_send_result=(True, "attention"))
        agent = _make_agent(insight_tracker=tracker)
        result = await agent.scan_patient("p1")

        assert len(result.insights) == 2
        # Both insights should have escalated severity
        for insight in result.insights:
            assert insight.severity == InsightSeverity.ATTENTION

    @pytest.mark.asyncio
    async def test_tracker_escalates_to_warning(self):
        """InsightTracker escalates to warning for 5+ day patterns."""
        tracker = _make_insight_tracker(should_send_result=(True, "warning"))
        agent = _make_agent(insight_tracker=tracker)
        result = await agent.scan_patient("p1")

        for insight in result.insights:
            assert insight.severity == InsightSeverity.WARNING

    @pytest.mark.asyncio
    async def test_tracker_records_after_send(self):
        """InsightTracker.record() is called with correct args after send."""
        tracker = _make_insight_tracker(should_send_result=(True, "info"))
        agent = _make_agent(insight_tracker=tracker)
        await agent.scan_patient("p1")

        # Verify record was called with patient_id and category
        first_record_call = tracker.record.call_args_list[0]
        assert first_record_call[0][0] == "p1"  # patient_id
        assert first_record_call[0][1] == "glucose_spike"  # category

    @pytest.mark.asyncio
    async def test_tracker_error_is_fail_open(self):
        """If InsightTracker errors, insights still pass through (fail-open)."""
        tracker = AsyncMock(spec=InsightTracker)
        tracker.should_send = AsyncMock(side_effect=Exception("DB timeout"))
        agent = _make_agent(insight_tracker=tracker)
        result = await agent.scan_patient("p1")

        # Fail-open: insights should still be delivered
        assert len(result.insights) == 2

    @pytest.mark.asyncio
    async def test_events_published_only_for_filtered_insights(self):
        """EventBus.publish() should only be called for insights that pass dedup."""
        tracker = _make_insight_tracker(should_send_result=(False, "info"))
        event_bus = _make_event_bus()
        agent = _make_agent(insight_tracker=tracker, event_bus=event_bus)
        await agent.scan_patient("p1")

        # All insights were blocked, so no events should be published
        assert event_bus.publish.call_count == 0

    @pytest.mark.asyncio
    async def test_mixed_dedup_results(self):
        """Some insights pass, some are blocked."""
        tracker = AsyncMock(spec=InsightTracker)
        # First insight: allow; Second insight: block
        tracker.should_send = AsyncMock(side_effect=[(True, "info"), (False, "info")])
        tracker.record = AsyncMock()
        tracker.ensure_indexes = AsyncMock()

        agent = _make_agent(insight_tracker=tracker)
        result = await agent.scan_patient("p1")

        assert len(result.insights) == 1
        assert tracker.record.call_count == 1


# ---------------------------------------------------------------------------
# InsightTracker Unit Tests
# ---------------------------------------------------------------------------


class TestInsightTracker:
    """Unit tests for InsightTracker with mocked MongoDB."""

    @pytest.mark.asyncio
    async def test_first_time_insight_should_send(self):
        """First insight for a patient+category should always send as INFO."""
        store, collection = _make_mock_mongo_store()
        collection.find_one = AsyncMock(return_value=None)

        tracker = InsightTracker(store)
        should_send, severity = await tracker.should_send("p1", "glucose_spike")

        assert should_send is True
        assert severity == "info"

    @pytest.mark.asyncio
    async def test_dedup_within_24h(self):
        """Insight sent less than 24h ago should be blocked."""
        store, collection = _make_mock_mongo_store()
        now = datetime.now(timezone.utc)
        collection.find_one = AsyncMock(return_value={
            "patient_id": "p1",
            "category": "glucose_spike",
            "severity": "info",
            "created_at": now - timedelta(hours=12),  # 12h ago
            "consecutive_days": 1,
        })

        tracker = InsightTracker(store)
        should_send, severity = await tracker.should_send("p1", "glucose_spike")

        assert should_send is False
        assert severity == "info"

    @pytest.mark.asyncio
    async def test_allow_after_24h(self):
        """Insight sent more than 24h ago should be allowed."""
        store, collection = _make_mock_mongo_store()
        now = datetime.now(timezone.utc)
        collection.find_one = AsyncMock(return_value={
            "patient_id": "p1",
            "category": "glucose_spike",
            "severity": "info",
            "created_at": now - timedelta(hours=25),
            "consecutive_days": 1,
        })

        tracker = InsightTracker(store)
        should_send, severity = await tracker.should_send("p1", "glucose_spike")

        assert should_send is True
        assert severity == "info"

    @pytest.mark.asyncio
    async def test_escalate_to_attention_after_3_days(self):
        """3 consecutive days should escalate to 'attention'."""
        store, collection = _make_mock_mongo_store()
        now = datetime.now(timezone.utc)
        collection.find_one = AsyncMock(return_value={
            "patient_id": "p1",
            "category": "glucose_spike",
            "severity": "info",
            "created_at": now - timedelta(hours=25),
            "consecutive_days": 2,  # +1 = 3 total
        })

        tracker = InsightTracker(store)
        should_send, severity = await tracker.should_send("p1", "glucose_spike")

        assert should_send is True
        assert severity == "attention"

    @pytest.mark.asyncio
    async def test_escalate_to_warning_after_5_days(self):
        """5 consecutive days should escalate to 'warning'."""
        store, collection = _make_mock_mongo_store()
        now = datetime.now(timezone.utc)
        collection.find_one = AsyncMock(return_value={
            "patient_id": "p1",
            "category": "glucose_spike",
            "severity": "attention",
            "created_at": now - timedelta(hours=25),
            "consecutive_days": 4,  # +1 = 5 total
        })

        tracker = InsightTracker(store)
        should_send, severity = await tracker.should_send("p1", "glucose_spike")

        assert should_send is True
        assert severity == "warning"

    @pytest.mark.asyncio
    async def test_escalation_at_boundary_4_days_is_attention(self):
        """4 consecutive days is still 'attention', not yet 'warning'."""
        store, collection = _make_mock_mongo_store()
        now = datetime.now(timezone.utc)
        collection.find_one = AsyncMock(return_value={
            "patient_id": "p1",
            "category": "glucose_spike",
            "severity": "info",
            "created_at": now - timedelta(hours=25),
            "consecutive_days": 3,  # +1 = 4 total
        })

        tracker = InsightTracker(store)
        _, severity = await tracker.should_send("p1", "glucose_spike")
        assert severity == "attention"

    @pytest.mark.asyncio
    async def test_record_first_insight(self):
        """Recording the first insight sets consecutive_days=1."""
        store, collection = _make_mock_mongo_store()
        collection.find_one = AsyncMock(return_value=None)

        tracker = InsightTracker(store)
        await tracker.record("p1", "glucose_spike", "info", "test message")

        collection.insert_one.assert_called_once()
        doc = collection.insert_one.call_args[0][0]
        assert doc["patient_id"] == "p1"
        assert doc["category"] == "glucose_spike"
        assert doc["severity"] == "info"
        assert doc["message"] == "test message"
        assert doc["consecutive_days"] == 1

    @pytest.mark.asyncio
    async def test_record_consecutive_within_48h(self):
        """Recording within 48h of last insight increments consecutive count."""
        store, collection = _make_mock_mongo_store()
        now = datetime.now(timezone.utc)
        collection.find_one = AsyncMock(return_value={
            "patient_id": "p1",
            "category": "glucose_spike",
            "created_at": now - timedelta(hours=25),
            "consecutive_days": 2,
        })

        tracker = InsightTracker(store)
        await tracker.record("p1", "glucose_spike", "attention", "test")

        doc = collection.insert_one.call_args[0][0]
        assert doc["consecutive_days"] == 3

    @pytest.mark.asyncio
    async def test_record_resets_after_48h_gap(self):
        """Recording after 48h gap resets consecutive count to 1."""
        store, collection = _make_mock_mongo_store()
        now = datetime.now(timezone.utc)
        collection.find_one = AsyncMock(return_value={
            "patient_id": "p1",
            "category": "glucose_spike",
            "created_at": now - timedelta(hours=50),  # > 48h ago
            "consecutive_days": 5,
        })

        tracker = InsightTracker(store)
        await tracker.record("p1", "glucose_spike", "info", "test")

        doc = collection.insert_one.call_args[0][0]
        assert doc["consecutive_days"] == 1

    @pytest.mark.asyncio
    async def test_ensure_indexes_creates_compound_and_ttl(self):
        """ensure_indexes() creates the compound lookup index and TTL index."""
        store, collection = _make_mock_mongo_store()
        tracker = InsightTracker(store)

        await tracker.ensure_indexes()

        assert collection.create_index.call_count == 2
        # Verify compound index
        first_call = collection.create_index.call_args_list[0]
        assert first_call[0][0] == [
            ("patient_id", 1), ("category", 1), ("created_at", -1),
        ]
        assert first_call[1]["name"] == "insight_patient_category_idx"
        # Verify TTL index
        second_call = collection.create_index.call_args_list[1]
        assert second_call[0][0] == "created_at"
        assert second_call[1]["expireAfterSeconds"] == _TTL_SECONDS

    @pytest.mark.asyncio
    async def test_collection_name_is_correct(self):
        """InsightTracker uses the expected collection name."""
        store, _ = _make_mock_mongo_store()
        InsightTracker(store)
        store.get_collection.assert_called_once_with(COLLECTION_NAME)

    @pytest.mark.asyncio
    async def test_indexes_lazy_on_first_call(self):
        """Indexes are created lazily on first should_send/record call."""
        store, collection = _make_mock_mongo_store()
        tracker = InsightTracker(store)

        # Indexes not yet created
        assert collection.create_index.call_count == 0

        # First call triggers index creation
        await tracker.should_send("p1", "glucose_spike")
        assert collection.create_index.call_count == 2

        # Second call does NOT re-create indexes
        await tracker.should_send("p1", "glucose_spike")
        assert collection.create_index.call_count == 2

    @pytest.mark.asyncio
    async def test_different_categories_are_independent(self):
        """Dedup for one category does not affect another."""
        store, collection = _make_mock_mongo_store()
        now = datetime.now(timezone.utc)

        # Return recent record for glucose_spike, nothing for meal_missed
        async def find_side_effect(filter_dict, **kwargs):
            if filter_dict.get("category") == "glucose_spike":
                return {
                    "patient_id": "p1",
                    "category": "glucose_spike",
                    "severity": "info",
                    "created_at": now - timedelta(hours=12),
                    "consecutive_days": 1,
                }
            return None

        collection.find_one = AsyncMock(side_effect=find_side_effect)

        tracker = InsightTracker(store)

        # glucose_spike should be blocked (sent 12h ago)
        should_send_spike, _ = await tracker.should_send("p1", "glucose_spike")
        assert should_send_spike is False

        # meal_missed should be allowed (never sent)
        should_send_meal, _ = await tracker.should_send("p1", "meal_missed")
        assert should_send_meal is True

    @pytest.mark.asyncio
    async def test_different_patients_are_independent(self):
        """Dedup for one patient does not affect another."""
        store, collection = _make_mock_mongo_store()
        now = datetime.now(timezone.utc)

        async def find_side_effect(filter_dict, **kwargs):
            if filter_dict.get("patient_id") == "p1":
                return {
                    "patient_id": "p1",
                    "category": "glucose_spike",
                    "severity": "info",
                    "created_at": now - timedelta(hours=12),
                    "consecutive_days": 1,
                }
            return None

        collection.find_one = AsyncMock(side_effect=find_side_effect)
        tracker = InsightTracker(store)

        should_send_p1, _ = await tracker.should_send("p1", "glucose_spike")
        assert should_send_p1 is False

        should_send_p2, _ = await tracker.should_send("p2", "glucose_spike")
        assert should_send_p2 is True


# ---------------------------------------------------------------------------
# Timezone-aware scheduling tests
# ---------------------------------------------------------------------------


class TestTimezoneScheduling:
    """Tests for the timezone-aware scan window logic in scheduling.py."""

    def test_within_scan_window_morning(self):
        """9 AM local time is within the scan window."""
        from zoneinfo import ZoneInfo
        from lib.ai_foundation.agents.proactive_monitor.scheduling import is_within_scan_window

        # 9 AM IST
        morning = datetime(2026, 3, 26, 9, 0, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
        assert is_within_scan_window("Asia/Kolkata", now=morning) is True

    def test_outside_scan_window_late_night(self):
        """2 AM local time is outside the scan window."""
        from zoneinfo import ZoneInfo
        from lib.ai_foundation.agents.proactive_monitor.scheduling import is_within_scan_window

        late_night = datetime(2026, 3, 26, 2, 0, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
        assert is_within_scan_window("Asia/Kolkata", now=late_night) is False

    def test_outside_scan_window_early_morning(self):
        """5 AM local time is outside the scan window."""
        from zoneinfo import ZoneInfo
        from lib.ai_foundation.agents.proactive_monitor.scheduling import is_within_scan_window

        early = datetime(2026, 3, 26, 5, 0, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
        assert is_within_scan_window("Asia/Kolkata", now=early) is False

    def test_boundary_start_of_window(self):
        """7 AM local time is the start of the window (inclusive)."""
        from zoneinfo import ZoneInfo
        from lib.ai_foundation.agents.proactive_monitor.scheduling import is_within_scan_window

        at_7am = datetime(2026, 3, 26, 7, 0, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
        assert is_within_scan_window("Asia/Kolkata", now=at_7am) is True

    def test_boundary_end_of_window(self):
        """10 PM (22:00) local time is the end of the window (exclusive)."""
        from zoneinfo import ZoneInfo
        from lib.ai_foundation.agents.proactive_monitor.scheduling import is_within_scan_window

        at_10pm = datetime(2026, 3, 26, 22, 0, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
        assert is_within_scan_window("Asia/Kolkata", now=at_10pm) is False

    def test_just_before_end_of_window(self):
        """9:59 PM is still within the scan window."""
        from zoneinfo import ZoneInfo
        from lib.ai_foundation.agents.proactive_monitor.scheduling import is_within_scan_window

        at_959pm = datetime(2026, 3, 26, 21, 59, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
        assert is_within_scan_window("Asia/Kolkata", now=at_959pm) is True

    def test_default_timezone_used_when_none(self):
        """When tz_name is None, defaults to Asia/Kolkata."""
        from zoneinfo import ZoneInfo
        from lib.ai_foundation.agents.proactive_monitor.scheduling import (
            is_within_scan_window,
            DEFAULT_TIMEZONE,
        )

        # 10 AM in IST
        morning_ist = datetime(2026, 3, 26, 10, 0, 0, tzinfo=ZoneInfo(DEFAULT_TIMEZONE))
        assert is_within_scan_window(None, now=morning_ist) is True

    def test_invalid_timezone_falls_back_to_default(self):
        """Invalid timezone string falls back to default."""
        from zoneinfo import ZoneInfo
        from lib.ai_foundation.agents.proactive_monitor.scheduling import (
            is_within_scan_window,
            DEFAULT_TIMEZONE,
        )

        # 10 AM in IST
        morning_ist = datetime(2026, 3, 26, 10, 0, 0, tzinfo=ZoneInfo(DEFAULT_TIMEZONE))
        assert is_within_scan_window("Invalid/Timezone", now=morning_ist) is True

    def test_different_timezone_new_york(self):
        """Test with America/New_York timezone."""
        from zoneinfo import ZoneInfo
        from lib.ai_foundation.agents.proactive_monitor.scheduling import is_within_scan_window

        # 3 AM in New York
        ny_3am = datetime(2026, 3, 26, 3, 0, 0, tzinfo=ZoneInfo("America/New_York"))
        assert is_within_scan_window("America/New_York", now=ny_3am) is False

        # 10 AM in New York
        ny_10am = datetime(2026, 3, 26, 10, 0, 0, tzinfo=ZoneInfo("America/New_York"))
        assert is_within_scan_window("America/New_York", now=ny_10am) is True

    def test_utc_time_converted_to_local(self):
        """A UTC datetime should be converted to the target timezone."""
        from zoneinfo import ZoneInfo
        from lib.ai_foundation.agents.proactive_monitor.scheduling import is_within_scan_window

        # 1:30 AM UTC = 7:00 AM IST (India is UTC+5:30)
        utc_time = datetime(2026, 3, 26, 1, 30, 0, tzinfo=ZoneInfo("UTC"))
        assert is_within_scan_window("Asia/Kolkata", now=utc_time) is True

        # 0:00 AM UTC = 5:30 AM IST (before window)
        utc_midnight = datetime(2026, 3, 26, 0, 0, 0, tzinfo=ZoneInfo("UTC"))
        assert is_within_scan_window("Asia/Kolkata", now=utc_midnight) is False

    def test_constants_exported(self):
        """Verify scheduling constants are accessible."""
        from lib.ai_foundation.agents.proactive_monitor.scheduling import (
            SCAN_WINDOW_START,
            SCAN_WINDOW_END,
            DEFAULT_TIMEZONE,
        )
        assert SCAN_WINDOW_START == 7
        assert SCAN_WINDOW_END == 22
        assert DEFAULT_TIMEZONE == "Asia/Kolkata"


# ---------------------------------------------------------------------------
# Prompt loading
# ---------------------------------------------------------------------------


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
