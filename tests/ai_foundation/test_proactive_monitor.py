"""Tests for the Proactive Monitor Agent (v2 — direct Qdrant fetch + single LLM)."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
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
    SEVERITY_RANK,
    LLM_INSIGHT_CATEGORIES_PROMPT,
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
from lib.ai_foundation.retrieval.base import RetrievalResult


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------


class TestContracts:
    def test_health_insight_defaults(self):
        hi = HealthInsight(
            category=InsightCategory.GLUCOSE_SPIKE,
            severity=InsightSeverity.WARNING,
            title="Test",
            body="Test body",
        )
        assert hi.patient_id == ""
        assert hi.actionable is True
        assert hi.data == {}
        assert hi.insight_id.startswith("ins_")

    def test_health_insight_default_patient_id(self):
        hi = HealthInsight(
            category=InsightCategory.MEAL_HIGH_CARB,
            severity=InsightSeverity.ATTENTION,
            title="Test",
            body="Test body",
            patient_id="p123",
        )
        assert hi.patient_id == "p123"

    def test_scan_result_properties(self):
        insights = [
            HealthInsight(category=InsightCategory.GLUCOSE_SPIKE, severity=InsightSeverity.WARNING, title="T", body="B"),
            HealthInsight(category=InsightCategory.FITNESS_STREAK, severity=InsightSeverity.INFO, title="T", body="B"),
        ]
        sr = ScanResult(patient_id="p1", insights=insights, scan_date="2026-03-28")
        assert sr.has_insights is True
        assert sr.alert_count == 1  # only WARNING counts

    def test_scan_result_no_insights(self):
        sr = ScanResult(patient_id="p1")
        assert sr.has_insights is False
        assert sr.alert_count == 0

    def test_batch_scan_result(self):
        b = BatchScanResult(total_patients=5)
        assert b.scanned == 0
        assert b.results == []

    def test_scan_insights_model(self):
        si = ScanInsights(insights=[
            HealthInsight(category=InsightCategory.GENERAL, severity=InsightSeverity.INFO, title="T", body="B"),
        ])
        assert len(si.insights) == 1

    def test_severity_rank(self):
        assert SEVERITY_RANK["alert"] > SEVERITY_RANK["warning"]
        assert SEVERITY_RANK["warning"] > SEVERITY_RANK["attention"]
        assert SEVERITY_RANK["attention"] > SEVERITY_RANK["info"]

    def test_llm_categories_prompt_has_concerns_and_positives(self):
        assert "Concerns:" in LLM_INSIGHT_CATEGORIES_PROMPT
        assert "Positives:" in LLM_INSIGHT_CATEGORIES_PROMPT
        assert "glucose_spike" in LLM_INSIGHT_CATEGORIES_PROMPT
        assert "glucose_improving" in LLM_INSIGHT_CATEGORIES_PROMPT


# ---------------------------------------------------------------------------
# Agent helpers
# ---------------------------------------------------------------------------


def _make_default_insights() -> list[HealthInsight]:
    return [
        HealthInsight(
            category=InsightCategory.GLUCOSE_SPIKE,
            severity=InsightSeverity.ATTENTION,
            title="🔴 Recurring glucose spikes",
            body="Good morning! You've had 3 post-meal spikes yesterday.",
            suggested_query="Show me my glucose spikes",
        ),
        HealthInsight(
            category=InsightCategory.FITNESS_STREAK,
            severity=InsightSeverity.INFO,
            title="✅ 5-day activity streak!",
            body="Good morning! Great job — you've been active for 5 days!",
            actionable=False,
        ),
    ]


def _make_qdrant(results: list[RetrievalResult] | None = None):
    """Mock QdrantRetriever that returns fake results."""
    qdrant = AsyncMock()
    qdrant.retrieve_filtered = AsyncMock(return_value=results if results is not None else [
        RetrievalResult(
            payload={"data_type": "meal", "date": "2026-03-27", "name": "Lunch", "nutrition": {"carbs": 80}},
            source="qdrant_filtered",
            data_type="meal",
        ),
        RetrievalResult(
            payload={"data_type": "fitness_overview", "date": "2026-03-27", "steps": 5000},
            source="qdrant_filtered",
            data_type="fitness_overview",
        ),
    ])
    return qdrant


def _make_gateway(insights: list[HealthInsight] | None = None):
    """Mock gateway that returns correct model based on response_model param."""
    from lib.ai_foundation.agents.proactive_monitor.contracts import DailyBrief

    gateway = AsyncMock()
    default_insights = insights if insights is not None else _make_default_insights()
    scan_insights = ScanInsights(insights=default_insights)
    daily_brief = DailyBrief(
        title="📋 Your health recap",
        body="Good morning! Here's your daily summary.",
        categories_covered=[i.category for i in default_insights],
        top_severity=max((i.severity for i in default_insights), key=lambda s: SEVERITY_RANK[s.value], default=InsightSeverity.INFO),
        suggested_query="How was my health yesterday?",
    )
    meta = LLMResponse(
        content="{}", model_id="gpt-4.1-mini",
        usage=LLMUsage(input_tokens=300, output_tokens=100, cost=CostBreakdown(total_cost=0.001)),
    )

    async def _extract(*, messages, response_model, **kwargs):
        if response_model is DailyBrief:
            return daily_brief, meta
        return scan_insights, meta

    gateway.extract = AsyncMock(side_effect=_extract)
    gateway.set_langfuse_context = MagicMock()
    gateway.langfuse_trace_input = MagicMock()
    gateway.langfuse_trace_output = MagicMock()
    return gateway


def _make_memory():
    memory = AsyncMock()
    memory.get_patient_facts = AsyncMock(return_value=[])
    return memory


def _make_event_bus():
    bus = AsyncMock()
    bus.publish = AsyncMock()
    return bus


def _make_insight_tracker(*, should_send_result=(True, "info", 1)):
    tracker = AsyncMock(spec=InsightTracker)
    tracker.should_send = AsyncMock(return_value=should_send_result)
    tracker.record = AsyncMock()
    tracker.ensure_indexes = AsyncMock()
    return tracker


def _make_agent(**overrides):
    return ProactiveMonitorAgent(
        gateway=overrides.get("gateway", _make_gateway()),
        qdrant=overrides.get("qdrant", _make_qdrant()),
        memory=overrides.get("memory", _make_memory()),
        event_bus=overrides.get("event_bus", _make_event_bus()),
        insight_tracker=overrides.get("insight_tracker", None),
    )


# ---------------------------------------------------------------------------
# InsightTracker — mock MongoDB collection
# ---------------------------------------------------------------------------


def _make_mock_mongo_store():
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
        assert len(result.insights) >= 1
        assert result.insights[0].patient_id == "p123"
        assert result.scan_duration_ms >= 0
        assert result.scan_date != ""
        assert result.error is None

    @pytest.mark.asyncio
    async def test_scan_patient_without_name(self):
        agent = _make_agent()
        result = await agent.scan_patient("p123")
        assert result.patient_id == "p123"
        assert result.has_insights is True

    @pytest.mark.asyncio
    async def test_scan_fetches_from_qdrant(self):
        qdrant = _make_qdrant()
        agent = _make_agent(qdrant=qdrant)
        await agent.scan_patient("p123", "Sarah")

        qdrant.retrieve_filtered.assert_called_once()
        call_args = qdrant.retrieve_filtered.call_args[0][0]
        assert call_args.patient_ids == ["p123"]
        assert "meal" in call_args.data_types

    @pytest.mark.asyncio
    async def test_scan_patient_no_data(self):
        """No data in Qdrant → engagement_drop insight without LLM."""
        qdrant = _make_qdrant(results=[])
        gateway = _make_gateway()
        agent = _make_agent(qdrant=qdrant, gateway=gateway)
        result = await agent.scan_patient("p_empty", "Sarah")

        assert result.data_available is False
        assert result.has_insights is True
        assert result.insights[0].category == InsightCategory.ENGAGEMENT_DROP
        # Gateway.extract should NOT be called (no-data path skips LLM)
        gateway.extract.assert_not_called()

    @pytest.mark.asyncio
    async def test_scan_llm_failure_fallback(self):
        """If LLM extraction fails, return static fallback insight."""
        gateway = AsyncMock()
        gateway.extract = AsyncMock(side_effect=Exception("LLM down"))
        gateway.set_langfuse_context = MagicMock()
        gateway.langfuse_trace_input = MagicMock()
        gateway.langfuse_trace_output = MagicMock()

        agent = _make_agent(gateway=gateway)
        result = await agent.scan_patient("p_fail", "Sarah")

        assert result.error is None  # outer scan didn't crash
        assert result.has_insights is True
        assert result.insights[0].category == InsightCategory.GENERAL
        assert "health check" in result.insights[0].title.lower() or "morning brief" in result.insights[0].title.lower()

    @pytest.mark.asyncio
    async def test_scan_publishes_events(self):
        event_bus = _make_event_bus()
        agent = _make_agent(event_bus=event_bus)
        await agent.scan_patient("p123")

        assert event_bus.publish.call_count >= 1
        published_event = event_bus.publish.call_args_list[0][0][0]
        assert published_event.event_type == "proactive_insight"
        assert published_event.patient_id == "p123"

    @pytest.mark.asyncio
    async def test_scan_batch(self):
        agent = _make_agent()
        batch = await agent.scan_batch(["p1", "p2", "p3"])

        assert batch.total_patients == 3
        assert batch.scanned == 3
        assert batch.with_insights == 3
        assert batch.total_insights >= 3  # at least 1 per patient

    @pytest.mark.asyncio
    async def test_scan_batch_with_names_and_timezones(self):
        agent = _make_agent()
        batch = await agent.scan_batch(
            ["p1", "p2"],
            patient_names={"p1": "Alice", "p2": "Bob"},
            patient_timezones={"p1": "Asia/Kolkata", "p2": "Europe/London"},
        )
        assert batch.scanned == 2

    @pytest.mark.asyncio
    async def test_scan_handles_qdrant_error(self):
        qdrant = AsyncMock()
        qdrant.retrieve_filtered = AsyncMock(side_effect=Exception("Qdrant down"))
        agent = _make_agent(qdrant=qdrant)
        result = await agent.scan_patient("p_error")

        assert result.error is not None
        assert "Qdrant down" in result.error
        assert result.data_available is False

    @pytest.mark.asyncio
    async def test_no_event_bus_still_works(self):
        agent = _make_agent(event_bus=None)
        result = await agent.scan_patient("p1")
        assert result.has_insights

    @pytest.mark.asyncio
    async def test_no_memory_still_works(self):
        agent = _make_agent(memory=None)
        result = await agent.scan_patient("p1")
        assert result.has_insights

    @pytest.mark.asyncio
    async def test_patient_id_stamped_on_insights(self):
        agent = _make_agent()
        result = await agent.scan_patient("p999")
        for insight in result.insights:
            assert insight.patient_id == "p999"

    @pytest.mark.asyncio
    async def test_record_insight(self):
        tracker = _make_insight_tracker()
        agent = _make_agent(insight_tracker=tracker)
        insight = _make_default_insights()[0]
        insight.patient_id = "p1"

        await agent.record_insight("p1", insight)
        tracker.record.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_interface(self):
        agent = _make_agent()
        input = AgentInput(message="scan", context=AgentContext(patient_id="p123"))
        output = await agent.run(input)
        assert output.is_ready is True

    @pytest.mark.asyncio
    async def test_run_no_patient_id(self):
        agent = _make_agent()
        input = AgentInput(message="scan", context=AgentContext())
        output = await agent.run(input)
        assert output.is_ready is False


# ---------------------------------------------------------------------------
# Dedup + Escalation Integration Tests
# ---------------------------------------------------------------------------


class TestDedupEscalationIntegration:
    @pytest.mark.asyncio
    async def test_no_tracker_passes_all_insights(self):
        agent = _make_agent(insight_tracker=None)
        result = await agent.scan_patient("p1")
        assert len(result.insights) >= 1

    @pytest.mark.asyncio
    async def test_tracker_allows_first_time_insights(self):
        tracker = _make_insight_tracker(should_send_result=(True, "info", 1))
        agent = _make_agent(insight_tracker=tracker)
        result = await agent.scan_patient("p1")
        assert len(result.insights) >= 1

    @pytest.mark.asyncio
    async def test_tracker_blocks_duplicate_insights(self):
        tracker = _make_insight_tracker(should_send_result=(False, "info", 1))
        agent = _make_agent(insight_tracker=tracker)
        result = await agent.scan_patient("p1")
        assert len(result.insights) == 0  # all blocked by dedup

    @pytest.mark.asyncio
    async def test_tracker_escalates_severity(self):
        tracker = _make_insight_tracker(should_send_result=(True, "attention", 3))
        agent = _make_agent(insight_tracker=tracker)
        result = await agent.scan_patient("p1")
        for insight in result.insights:
            # Morning briefs use LLM-set severity; afternoon insights get escalated
            assert insight.severity.value in ("attention", "info")

    @pytest.mark.asyncio
    async def test_tracker_never_downgrades_warning(self):
        tracker = _make_insight_tracker(should_send_result=(True, "attention", 3))
        warning_only = [
            HealthInsight(
                category=InsightCategory.GLUCOSE_SPIKE,
                severity=InsightSeverity.WARNING,
                title="Spike",
                body="High glucose after lunch.",
            ),
        ]
        agent = _make_agent(insight_tracker=tracker, gateway=_make_gateway(insights=warning_only))
        result = await agent.scan_patient("p1")
        assert result.insights[0].severity == InsightSeverity.WARNING


# ---------------------------------------------------------------------------
# InsightTracker
# ---------------------------------------------------------------------------


class TestInsightTracker:
    @pytest.mark.asyncio
    async def test_first_time_insight_should_send(self):
        store, collection = _make_mock_mongo_store()
        collection.find_one = AsyncMock(return_value=None)
        tracker = InsightTracker(store)
        should_send, severity, _ = await tracker.should_send("p1", "glucose_spike")
        assert should_send is True
        assert severity == "info"

    @pytest.mark.asyncio
    async def test_dedup_within_24h(self):
        store, collection = _make_mock_mongo_store()
        now = datetime.now(timezone.utc)
        collection.find_one = AsyncMock(return_value={
            "created_at": now - timedelta(hours=12),
            "severity": "info",
            "consecutive_days": 1,
        })
        tracker = InsightTracker(store)
        should_send, _, _ = await tracker.should_send("p1", "glucose_spike")
        assert should_send is False

    @pytest.mark.asyncio
    async def test_allow_after_24h(self):
        store, collection = _make_mock_mongo_store()
        now = datetime.now(timezone.utc)
        collection.find_one = AsyncMock(return_value={
            "created_at": now - timedelta(hours=25),
            "severity": "info",
            "consecutive_days": 1,
        })
        tracker = InsightTracker(store)
        should_send, severity, _ = await tracker.should_send("p1", "glucose_spike")
        assert should_send is True
        assert severity == "info"

    @pytest.mark.asyncio
    async def test_escalate_to_attention_after_3_days(self):
        store, collection = _make_mock_mongo_store()
        now = datetime.now(timezone.utc)
        collection.find_one = AsyncMock(return_value={
            "created_at": now - timedelta(hours=25),
            "severity": "info",
            "consecutive_days": 2,  # +1 = 3
        })
        tracker = InsightTracker(store)
        _, severity, _ = await tracker.should_send("p1", "glucose_spike")
        assert severity == "attention"

    @pytest.mark.asyncio
    async def test_escalate_to_warning_after_5_days(self):
        store, collection = _make_mock_mongo_store()
        now = datetime.now(timezone.utc)
        collection.find_one = AsyncMock(return_value={
            "created_at": now - timedelta(hours=25),
            "severity": "attention",
            "consecutive_days": 4,  # +1 = 5
        })
        tracker = InsightTracker(store)
        _, severity, _ = await tracker.should_send("p1", "glucose_spike")
        assert severity == "warning"

    @pytest.mark.asyncio
    async def test_should_send_resets_stale_consecutive_days(self):
        store, collection = _make_mock_mongo_store()
        now = datetime.now(timezone.utc)
        collection.find_one = AsyncMock(return_value={
            "created_at": now - timedelta(hours=60),
            "severity": "warning",
            "consecutive_days": 5,
        })
        tracker = InsightTracker(store)
        should_send, severity, _ = await tracker.should_send("p1", "glucose_spike")
        assert should_send is True
        assert severity == "info"

    @pytest.mark.asyncio
    async def test_record_first_insight(self):
        store, collection = _make_mock_mongo_store()
        tracker = InsightTracker(store)
        await tracker.record("p1", "glucose_spike", "info", "test")
        collection.insert_one.assert_called_once()
        doc = collection.insert_one.call_args[0][0]
        assert doc["consecutive_days"] == 1
        assert doc["patient_id"] == "p1"

    @pytest.mark.asyncio
    async def test_record_with_extra_fields(self):
        store, collection = _make_mock_mongo_store()
        tracker = InsightTracker(store)
        await tracker.record("p1", "glucose_spike", "info", "test",
                             insight_id="ins_abc", title="Test", suggested_query="How?")
        doc = collection.insert_one.call_args[0][0]
        assert doc["insight_id"] == "ins_abc"
        assert doc["title"] == "Test"
        assert doc["suggested_query"] == "How?"

    @pytest.mark.asyncio
    async def test_record_stores_trace_id(self):
        store, collection = _make_mock_mongo_store()
        tracker = InsightTracker(store)
        await tracker.record("p1", "glucose_spike", "info", "test", trace_id="pm_trace_1")
        doc = collection.insert_one.call_args[0][0]
        assert doc["trace_id"] == "pm_trace_1"

    @pytest.mark.asyncio
    async def test_get_by_insight_id(self):
        store, collection = _make_mock_mongo_store()
        collection.find_one = AsyncMock(return_value={"_id": "mongo1", "insight_id": "ins_abc", "trace_id": "pm_trace_1"})
        tracker = InsightTracker(store)
        doc = await tracker.get_by_insight_id("ins_abc")
        assert doc["insight_id"] == "ins_abc"
        assert doc["trace_id"] == "pm_trace_1"

    @pytest.mark.asyncio
    async def test_record_consecutive_within_48h(self):
        store, collection = _make_mock_mongo_store()
        now = datetime.now(timezone.utc)
        collection.find_one = AsyncMock(return_value={
            "created_at": now - timedelta(hours=25),
            "consecutive_days": 2,
        })
        tracker = InsightTracker(store)
        await tracker.record("p1", "glucose_spike", "attention", "test")
        doc = collection.insert_one.call_args[0][0]
        assert doc["consecutive_days"] == 3

    @pytest.mark.asyncio
    async def test_record_resets_after_48h_gap(self):
        store, collection = _make_mock_mongo_store()
        now = datetime.now(timezone.utc)
        collection.find_one = AsyncMock(return_value={
            "created_at": now - timedelta(hours=50),
            "consecutive_days": 5,
        })
        tracker = InsightTracker(store)
        await tracker.record("p1", "glucose_spike", "info", "test")
        doc = collection.insert_one.call_args[0][0]
        assert doc["consecutive_days"] == 1

    @pytest.mark.asyncio
    async def test_ensure_indexes(self):
        store, collection = _make_mock_mongo_store()
        tracker = InsightTracker(store)
        await tracker.ensure_indexes()
        assert collection.create_index.call_count == 4

    @pytest.mark.asyncio
    async def test_collection_name(self):
        store, _ = _make_mock_mongo_store()
        InsightTracker(store)
        store.get_collection.assert_called_once_with(COLLECTION_NAME)


# ---------------------------------------------------------------------------
# Timezone Scheduling
# ---------------------------------------------------------------------------


class TestTimezoneScheduling:
    """Tests for scheduling.is_within_scan_window."""

    def test_within_window_morning(self):
        from lib.ai_foundation.agents.proactive_monitor.scheduling import is_within_scan_window
        from zoneinfo import ZoneInfo
        morning = datetime(2026, 3, 28, 9, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
        assert is_within_scan_window("Asia/Kolkata", now=morning) is True

    def test_outside_window_night(self):
        from lib.ai_foundation.agents.proactive_monitor.scheduling import is_within_scan_window
        from zoneinfo import ZoneInfo
        night = datetime(2026, 3, 28, 23, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
        assert is_within_scan_window("Asia/Kolkata", now=night) is False

    def test_outside_window_early_morning(self):
        from lib.ai_foundation.agents.proactive_monitor.scheduling import is_within_scan_window
        from zoneinfo import ZoneInfo
        early = datetime(2026, 3, 28, 5, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
        assert is_within_scan_window("Asia/Kolkata", now=early) is False

    def test_boundary_start(self):
        from lib.ai_foundation.agents.proactive_monitor.scheduling import is_within_scan_window
        from zoneinfo import ZoneInfo
        start = datetime(2026, 3, 28, 7, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
        assert is_within_scan_window("Asia/Kolkata", now=start) is True

    def test_boundary_end(self):
        from lib.ai_foundation.agents.proactive_monitor.scheduling import is_within_scan_window
        from zoneinfo import ZoneInfo
        end = datetime(2026, 3, 28, 22, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
        assert is_within_scan_window("Asia/Kolkata", now=end) is False

    def test_invalid_timezone_fallback(self):
        from lib.ai_foundation.agents.proactive_monitor.scheduling import is_within_scan_window
        # Should not crash — falls back to default timezone
        result = is_within_scan_window("Invalid/Timezone")
        assert isinstance(result, bool)

    def test_none_timezone_uses_default(self):
        from lib.ai_foundation.agents.proactive_monitor.scheduling import is_within_scan_window
        result = is_within_scan_window(None)
        assert isinstance(result, bool)
