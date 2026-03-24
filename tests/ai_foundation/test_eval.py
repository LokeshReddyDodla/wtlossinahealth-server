"""Tests for Evaluation — trace, collector, schemas, quality judges."""

import pytest
import asyncio

from lib.ai_foundation.eval.trace import Span, Trace, TraceCollector
from lib.ai_foundation.eval.collector import FinetuneDataCollector, TrainingSample, ImplicitSignals
from lib.ai_foundation.eval.schemas import (
    EvalCase,
    EvalResult,
    EvalRunSummary,
    EvalTaskType,
    JudgeVerdict,
)
from lib.ai_foundation.eval.quality import (
    QualityScore,
    judge_contains_keywords,
    judge_exact_match,
    judge_not_contains,
    judge_set_precision,
    judge_set_recall,
)


class TestTrace:
    def test_trace_has_id(self):
        t = Trace(agent_id="test")
        assert t.trace_id.startswith("trc_")
        assert t.agent_id == "test"

    def test_span_defaults(self):
        s = Span(name="intent_extraction")
        assert s.name == "intent_extraction"
        assert s.cache_hit is False
        assert s.error is None


class TestTraceCollector:
    @pytest.mark.asyncio
    async def test_start_and_finish(self):
        collector = TraceCollector()
        trace = collector.start_trace("test_agent", patient_id="p123")
        assert trace.agent_id == "test_agent"
        assert trace.patient_id_hash is not None
        assert trace.patient_id_hash != "p123"  # hashed

        async with collector.span("step_1") as s:
            s.cost_usd = 0.001
        async with collector.span("step_2") as s:
            s.cost_usd = 0.002

        finished = await collector.finish_trace()
        assert len(finished.spans) == 2
        assert finished.total_cost_usd == pytest.approx(0.003)
        assert finished.total_latency_ms >= 0

    @pytest.mark.asyncio
    async def test_span_records_error(self):
        collector = TraceCollector()
        collector.start_trace("test_agent")

        with pytest.raises(ValueError):
            async with collector.span("failing") as s:
                raise ValueError("test error")

        finished = await collector.finish_trace()
        assert finished.spans[0].error
        assert "test error" in finished.spans[0].error

    @pytest.mark.asyncio
    async def test_no_active_trace_raises(self):
        collector = TraceCollector()
        with pytest.raises(RuntimeError, match="No active trace"):
            async with collector.span("orphan"):
                pass

    @pytest.mark.asyncio
    async def test_first_token_recording(self):
        collector = TraceCollector()
        collector.start_trace("test")
        collector.record_first_token()
        assert collector.active_trace.first_token_ms is not None


class TestTrainingSample:
    def test_sample_id_generated(self):
        s = TrainingSample(
            agent_id="test", task="intent", model_id="gpt-4.1-mini",
            messages=[], response="test",
        )
        assert s.sample_id.startswith("smp_")

    def test_implicit_signals_default_none(self):
        signals = ImplicitSignals()
        assert signals.user_asked_clarification_after is None
        assert signals.care_provider_flagged is None


class TestFinetuneDataCollector:
    @pytest.mark.asyncio
    async def test_disabled_returns_none(self):
        collector = FinetuneDataCollector(enabled=False)
        result = await collector.record_sample(
            agent_id="test", task="intent", model_id="m",
            messages=[], response="r",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_no_mongo_returns_none(self):
        collector = FinetuneDataCollector(mongo_store=None, enabled=True)
        result = await collector.record_sample(
            agent_id="test", task="intent", model_id="m",
            messages=[], response="r",
        )
        assert result is None


class TestEvalSchemas:
    def test_eval_case(self):
        case = EvalCase(
            case_id="test-001",
            task_type=EvalTaskType.INTENT_EXTRACTION,
            input_query="Show me my glucose",
            expected_is_ready=True,
            expected_data_types=["cgm_range_stats"],
            tags=["cgm", "simple"],
        )
        assert case.case_id == "test-001"
        assert case.tags == ["cgm", "simple"]

    def test_eval_result_avg_score(self):
        result = EvalResult(
            case_id="test",
            task_type=EvalTaskType.INTENT_EXTRACTION,
            verdicts=[
                JudgeVerdict(metric_name="a", score=0.8, passed=True),
                JudgeVerdict(metric_name="b", score=0.6, passed=False, threshold=0.7),
            ],
        )
        assert result.avg_score == pytest.approx(0.7)

    def test_eval_run_summary_compute(self):
        summary = EvalRunSummary(task_type=EvalTaskType.INTENT_EXTRACTION)
        summary.results = [
            EvalResult(
                case_id="1", task_type=EvalTaskType.INTENT_EXTRACTION,
                passed=True, latency_ms=100,
                verdicts=[JudgeVerdict(metric_name="acc", score=0.9, passed=True)],
            ),
            EvalResult(
                case_id="2", task_type=EvalTaskType.INTENT_EXTRACTION,
                passed=False, latency_ms=200,
                verdicts=[JudgeVerdict(metric_name="acc", score=0.5, passed=False, threshold=0.8)],
            ),
        ]
        summary.compute_aggregates()
        assert summary.total_cases == 2
        assert summary.passed_cases == 1
        assert summary.pass_rate == 0.5
        assert summary.avg_latency_ms == 150.0
        assert summary.metrics["acc"] == pytest.approx(0.7)

    def test_summary_line(self):
        summary = EvalRunSummary(
            task_type=EvalTaskType.INTENT_EXTRACTION,
            model_used="gpt-4.1-mini",
        )
        summary.total_cases = 10
        summary.passed_cases = 8
        summary.pass_rate = 0.8
        summary.avg_latency_ms = 250.0
        line = summary.summary_line()
        assert "8/10" in line
        assert "80%" in line


class TestDeterministicJudges:
    def test_exact_match_pass(self):
        v = judge_exact_match("test", True, True)
        assert v.passed is True
        assert v.score == 1.0

    def test_exact_match_fail(self):
        v = judge_exact_match("test", True, False)
        assert v.passed is False
        assert v.score == 0.0

    def test_set_precision_perfect(self):
        v = judge_set_precision("prec", ["a", "b"], ["a", "b", "c"])
        assert v.score == 1.0
        assert v.passed is True

    def test_set_precision_partial(self):
        v = judge_set_precision("prec", ["a", "b", "x"], ["a", "b", "c"])
        assert v.score == pytest.approx(2 / 3, abs=0.01)

    def test_set_precision_empty_actual(self):
        v = judge_set_precision("prec", [], ["a", "b"])
        assert v.score == 0.0
        assert v.passed is False

    def test_set_recall_perfect(self):
        v = judge_set_recall("rec", ["a", "b", "c"], ["a", "b"])
        assert v.score == 1.0

    def test_set_recall_partial(self):
        v = judge_set_recall("rec", ["a"], ["a", "b"])
        assert v.score == 0.5

    def test_set_recall_empty_expected(self):
        v = judge_set_recall("rec", ["a"], [])
        assert v.score == 1.0  # vacuously true

    def test_contains_keywords_all(self):
        v = judge_contains_keywords("kw", "glucose was 145 mg/dL", ["glucose", "145"])
        assert v.score == 1.0

    def test_contains_keywords_partial(self):
        v = judge_contains_keywords("kw", "glucose was stable", ["glucose", "145", "mg/dL"])
        assert v.score == pytest.approx(1 / 3, abs=0.01)

    def test_not_contains_clean(self):
        v = judge_not_contains("no_halluc", "your glucose was good", ["insulin", "medication"])
        assert v.score == 1.0
        assert v.passed is True

    def test_not_contains_violation(self):
        v = judge_not_contains("no_halluc", "take insulin after meals", ["insulin"])
        assert v.score == 0.0
        assert v.passed is False


class TestQualityScore:
    def test_overall_weighted(self):
        qs = QualityScore(
            factual_grounding=0.9,
            completeness=0.8,
            tone=0.9,
            safety=1.0,
            conciseness=0.7,
        )
        assert 0.0 < qs.overall < 1.0

    def test_safety_weighted_higher(self):
        safe = QualityScore(safety=1.0, factual_grounding=0.5, completeness=0.5, tone=0.5, conciseness=0.5)
        unsafe = QualityScore(safety=0.0, factual_grounding=0.5, completeness=0.5, tone=0.5, conciseness=0.5)
        assert safe.overall > unsafe.overall
