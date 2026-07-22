"""Tests for the Proactive Monitor Agent (v2 — direct Qdrant fetch + single LLM)."""

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


def _make_health_agent(narration=None):
    """The one brain. run_proactive returns a push-shaped narration; the monitor
    stamps category/severity deterministically and wraps it in a ScanResult."""
    from lib.ai_foundation.agents.health_query.contracts import ProactiveNarration
    brain = AsyncMock()
    brain.run_proactive = AsyncMock(return_value=narration or ProactiveNarration(
        notify=True, title="Your check-in", body="Here's your day so far.",
        suggested_query="How am I doing?"))
    return brain


def _make_agent(**overrides):
    return ProactiveMonitorAgent(
        gateway=overrides.get("gateway", _make_gateway()),
        qdrant=overrides.get("qdrant", _make_qdrant()),
        memory=overrides.get("memory", _make_memory()),
        event_bus=overrides.get("event_bus", _make_event_bus()),
        insight_tracker=overrides.get("insight_tracker", None),
        health_agent=overrides.get("health_agent", _make_health_agent()),
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
    async def test_brain_declining_yields_no_digest(self):
        """When the brain judges nothing noteworthy, the cron scan sends nothing."""
        from lib.ai_foundation.agents.health_query.contracts import ProactiveNarration
        agent = _make_agent(health_agent=_make_health_agent(ProactiveNarration(notify=False)))
        result = await agent.scan_patient("p_empty", "Sarah")
        assert result.has_insights is False
        assert result.error is None

    @pytest.mark.asyncio
    async def test_scan_brain_failure_produces_no_insight(self):
        """A brain failure never crashes the scan; it just yields no insight."""
        brain = _make_health_agent()
        brain.run_proactive = AsyncMock(side_effect=Exception("brain down"))
        agent = _make_agent(health_agent=brain)
        result = await agent.scan_patient("p_fail", "Sarah")
        assert result.has_insights is False

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
        assert collection.create_index.call_count == 6

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


class TestMealTotalsComputed:
    """Meal arithmetic happens in code, not in the LLM — wrong sums in a
    notification are a clinical-credibility bug (dietitian review 30/06)."""

    def test_macros_from_production_nutrition_dict_and_flat_keys(self):
        prod = {"nutrition": {"calories": 480, "carbohydrates": 74, "proteins": 9, "fiber": 5}}
        flat = {"calories": 240, "carbs_g": 14, "protein_g": 11, "fiber_g": 5}
        assert ProactiveMonitorAgent._meal_macros(prod) == (480.0, 74.0, 9.0, 5.0)
        assert ProactiveMonitorAgent._meal_macros(flat) == (240.0, 14.0, 11.0, 5.0)
        assert ProactiveMonitorAgent._meal_macros({}) == (None, None, None, None)

    def test_sitting_totals_within_window_only(self):
        from lib.ai_foundation.agents.proactive_monitor.contracts import EventTrigger
        agent = _make_agent()
        t0 = 1_000_000_000_000.0
        trigger_rec = {"start_time": t0, "calories": 60, "carbs_g": 12, "protein_g": 2, "fiber_g": 4}
        meals = [
            {"start_time": t0 - 20 * 60 * 1000, "calories": 240, "carbs_g": 14, "protein_g": 11, "fiber_g": 5},
            {"start_time": t0 - 60 * 60 * 1000, "calories": 95, "carbs_g": 18, "protein_g": 3, "fiber_g": 1},
            # 7 hours earlier — a different meal, must NOT be in the sitting
            {"start_time": t0 - 7 * 3600 * 1000, "calories": 480, "carbs_g": 74, "protein_g": 9, "fiber_g": 5},
        ]
        section = agent._meal_totals_section(
            meals, trigger=EventTrigger.MEAL_LOGGED, trigger_record=trigger_rec,
            scan_date="2026-07-21",
        )
        assert "THIS SITTING" in section and "2 co-logged" in section
        assert "395 kcal" in section      # 60+240+95, excludes the 480
        assert "44g carbs" in section     # 12+14+18
        assert "16g protein" in section
        assert "10g fiber" in section

    def test_single_item_sitting_returns_none(self):
        from lib.ai_foundation.agents.proactive_monitor.contracts import EventTrigger
        agent = _make_agent()
        assert agent._meal_totals_section(
            [], trigger=EventTrigger.MEAL_LOGGED,
            trigger_record={"start_time": 1.0, "calories": 300},
            scan_date="2026-07-21",
        ) is None

    def test_cron_day_totals(self):
        agent = _make_agent()
        meals = [
            {"meal_date": "2026-07-21", "nutrition": {"calories": 180, "carbohydrates": 32, "proteins": 4, "fiber": 2}},
            {"meal_date": "2026-07-21", "nutrition": {"calories": 240, "carbohydrates": 38, "proteins": 9, "fiber": 5}},
        ]
        section = agent._meal_totals_section(
            meals, trigger=None, trigger_record=None, scan_date="2026-07-21",
        )
        assert "MEALS ON 2026-07-21" in section
        assert "420 kcal" in section and "13g protein" in section

    def test_day_total_excludes_other_days(self):
        """Event scans fetch two days of meals; the day total must count only
        the reported day, or the LLM reports the two-day sum as 'today'."""
        agent = _make_agent()
        meals = [
            {"meal_date": "2026-07-21", "nutrition": {"calories": 240, "carbohydrates": 38, "proteins": 27, "fiber": 5}},
            # yesterday's meals are context only — must not enter the total
            {"meal_date": "2026-07-20", "nutrition": {"calories": 500, "carbohydrates": 60, "proteins": 40, "fiber": 8}},
            {"meal_date": "2026-07-20", "nutrition": {"calories": 400, "carbohydrates": 50, "proteins": 26, "fiber": 7}},
        ]
        section = agent._meal_totals_section(
            meals, trigger=None, trigger_record=None, scan_date="2026-07-21",
        )
        assert "27g protein" in section          # today only
        assert "93g protein" not in section      # not the two-day sum
        assert "1 items" in section              # only the one Jul-21 meal counted

    def test_missing_macro_is_unknown_not_zero(self):
        """A record with no fiber field must not produce '0g fiber' — the
        LLM turns that into 'your meal had 0g fiber' (dietitian-visible bug)."""
        agent = _make_agent()
        meals = [
            {"meal_date": "2026-07-21", "calories": 320, "carbs_g": 28, "protein_g": 18},  # no fiber field
            {"meal_date": "2026-07-21", "calories": 200, "carbs_g": 30, "protein_g": 6},
        ]
        section = agent._meal_totals_section(
            meals, trigger=None, trigger_record=None, scan_date="2026-07-21",
        )
        assert "fiber" not in section
        assert "520 kcal" in section and "24g protein" in section

    def test_partial_macro_data_marked(self):
        agent = _make_agent()
        meals = [
            {"meal_date": "2026-07-21", "calories": 300, "fiber_g": 6},
            {"meal_date": "2026-07-21", "calories": 200},  # no fiber
        ]
        section = agent._meal_totals_section(
            meals, trigger=None, trigger_record=None, scan_date="2026-07-21",
        )
        assert "at least 6g fiber" in section
        assert "lack full macro data" in section
