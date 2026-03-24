"""Tests for Training Pipeline — curator, exporter, validator, A/B test."""

import json
from pathlib import Path

import pytest

from lib.ai_foundation.training.curator import (
    CurationStats,
    QualityFilter,
    SampleQualityScore,
)
from lib.ai_foundation.training.exporter import TrainingExporter
from lib.ai_foundation.training.validator import DatasetValidator, ValidationReport
from lib.ai_foundation.training.ab_test import ABTestConfig, ABTestManager
from lib.ai_foundation.models.registry import ModelTask


class TestSampleQualityScore:
    def test_eligible_good_sample(self):
        s = SampleQualityScore(
            sample_id="test",
            structural_valid=True,
            feedback_positive=True,
            no_negative_signals=True,
            eval_intent_accuracy=0.9,
            eval_safety=1.0,
            eval_grounding=0.85,
        )
        assert s.eligible is True
        assert s.composite_score >= 0.80

    def test_ineligible_structural_invalid(self):
        s = SampleQualityScore(
            sample_id="test",
            structural_valid=False,
            eval_safety=1.0,
            eval_intent_accuracy=0.9,
            eval_grounding=0.9,
        )
        assert s.eligible is False
        assert s.composite_score == 0.0

    def test_ineligible_negative_feedback(self):
        s = SampleQualityScore(
            sample_id="test",
            structural_valid=True,
            feedback_positive=False,
            eval_safety=1.0,
            eval_intent_accuracy=0.9,
            eval_grounding=0.9,
        )
        assert s.eligible is False

    def test_ineligible_safety_failed(self):
        s = SampleQualityScore(
            sample_id="test",
            structural_valid=True,
            eval_safety=0.5,
            eval_intent_accuracy=0.9,
            eval_grounding=0.9,
        )
        assert s.eligible is False

    def test_no_feedback_can_be_eligible(self):
        s = SampleQualityScore(
            sample_id="test",
            structural_valid=True,
            feedback_positive=None,
            no_negative_signals=True,
            eval_intent_accuracy=0.9,
            eval_safety=1.0,
            eval_grounding=0.9,
        )
        assert s.eligible is True

    def test_negative_signals_ineligible(self):
        s = SampleQualityScore(
            sample_id="test",
            structural_valid=True,
            no_negative_signals=False,
            eval_safety=1.0,
            eval_intent_accuracy=0.9,
            eval_grounding=0.9,
        )
        assert s.eligible is False


class TestQualityFilter:
    @pytest.mark.asyncio
    async def test_score_good_sample(self):
        f = QualityFilter()
        score = await f.score_sample({
            "sample_id": "s1",
            "response": "glucose was 145",
            "messages": [{"role": "user", "content": "test"}],
            "feedback_score": 1.0,
            "implicit_signals": {},
            "eval_scores": {"intent_accuracy": 0.95, "safety": 1.0, "factual_grounding": 0.9},
        })
        assert score.structural_valid is True
        assert score.feedback_positive is True
        assert score.eligible is True

    @pytest.mark.asyncio
    async def test_score_empty_response(self):
        f = QualityFilter()
        score = await f.score_sample({
            "sample_id": "s2",
            "response": "",
            "messages": [],
        })
        assert score.structural_valid is False


class TestTrainingExporter:
    def test_export_openai_jsonl(self, tmp_path):
        exporter = TrainingExporter(output_dir=tmp_path)
        samples = [
            {
                "messages": [
                    {"role": "system", "content": "Extract intent."},
                    {"role": "user", "content": "Show glucose"},
                ],
                "response": '{"is_ready": true}',
                "structured_output": {"data_types": ["cgm_range_stats"]},
            },
            {
                "messages": [
                    {"role": "system", "content": "Extract intent."},
                    {"role": "user", "content": "My meals today"},
                ],
                "response": '{"is_ready": true}',
                "structured_output": {"data_types": ["meal"]},
            },
        ]
        stats = exporter.export_openai_jsonl(samples, task="intent", val_ratio=0.5)
        assert stats.total_samples == 2
        assert stats.train_samples + stats.val_samples == 2

        # Verify file contents
        train_path = tmp_path / "intent_train.jsonl"
        assert train_path.exists()
        with open(train_path) as f:
            lines = f.readlines()
            for line in lines:
                data = json.loads(line)
                assert "messages" in data
                assert data["messages"][-1]["role"] == "assistant"

    def test_export_preference_pairs(self, tmp_path):
        exporter = TrainingExporter(output_dir=tmp_path)
        samples = [
            {"task": "response", "feedback_score": 1.0, "messages": [{"role": "user", "content": "q"}], "response": "good"},
            {"task": "response", "feedback_score": 0.0, "messages": [{"role": "user", "content": "q"}], "response": "bad"},
        ]
        stats = exporter.export_preference_pairs(samples, task="response")
        assert stats.total_samples == 1

        pair_path = tmp_path / "response_dpo_pairs.jsonl"
        assert pair_path.exists()
        with open(pair_path) as f:
            pair = json.loads(f.readline())
            assert pair["chosen"] == "good"
            assert pair["rejected"] == "bad"


class TestDatasetValidator:
    def test_valid_dataset(self, tmp_path):
        f = tmp_path / "train.jsonl"
        examples = [
            {"messages": [{"role": "system", "content": "sys"}, {"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}]},
        ] * 20
        with open(f, "w") as fp:
            for ex in examples:
                fp.write(json.dumps(ex) + "\n")

        v = DatasetValidator()
        report = v.validate_jsonl(f, min_examples=10)
        assert report.valid is True
        assert report.total_examples == 20
        assert report.error_count == 0

    def test_invalid_json(self, tmp_path):
        f = tmp_path / "bad.jsonl"
        f.write_text("not json\n")
        report = DatasetValidator().validate_jsonl(f, min_examples=0)
        assert report.error_count >= 1

    def test_missing_assistant(self, tmp_path):
        f = tmp_path / "no_assistant.jsonl"
        f.write_text(json.dumps({"messages": [{"role": "user", "content": "q"}]}) + "\n")
        report = DatasetValidator().validate_jsonl(f, min_examples=0)
        assert report.error_count >= 1

    def test_too_few_examples(self, tmp_path):
        f = tmp_path / "small.jsonl"
        f.write_text(json.dumps({"messages": [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}]}) + "\n")
        report = DatasetValidator().validate_jsonl(f, min_examples=10)
        assert report.valid is False

    def test_nonexistent_file(self, tmp_path):
        report = DatasetValidator().validate_jsonl(tmp_path / "ghost.jsonl")
        assert report.valid is False

    def test_duplicate_detection(self, tmp_path):
        f = tmp_path / "dupes.jsonl"
        line = json.dumps({"messages": [{"role": "user", "content": "same"}, {"role": "assistant", "content": "same"}]})
        f.write_text("\n".join([line] * 20) + "\n")
        report = DatasetValidator().validate_jsonl(f, min_examples=1)
        assert report.duplicate_count == 19


class TestABTestManager:
    @pytest.mark.asyncio
    async def test_create_and_route(self):
        mgr = ABTestManager()
        config = ABTestConfig(
            test_id="test-1",
            task=ModelTask.INTENT_EXTRACTION,
            control_model="gpt-4.1-mini",
            treatment_model="ft:gpt-4.1-mini:health-v1",
            traffic_split=1.0,  # 100% treatment for deterministic test
        )
        await mgr.create_test(config)
        model = await mgr.get_routing_decision(ModelTask.INTENT_EXTRACTION)
        assert model == "ft:gpt-4.1-mini:health-v1"

    @pytest.mark.asyncio
    async def test_no_test_returns_none(self):
        mgr = ABTestManager()
        model = await mgr.get_routing_decision(ModelTask.INTENT_EXTRACTION)
        assert model is None

    @pytest.mark.asyncio
    async def test_zero_split_routes_to_control(self):
        mgr = ABTestManager()
        await mgr.create_test(ABTestConfig(
            test_id="test-2",
            task=ModelTask.INTENT_EXTRACTION,
            control_model="control",
            treatment_model="treatment",
            traffic_split=0.0,
        ))
        model = await mgr.get_routing_decision(ModelTask.INTENT_EXTRACTION)
        assert model == "control"

    @pytest.mark.asyncio
    async def test_promote_treatment(self):
        mgr = ABTestManager()
        await mgr.create_test(ABTestConfig(
            test_id="test-3",
            task=ModelTask.RESPONSE_GENERATION,
            control_model="old",
            treatment_model="new",
            traffic_split=0.1,
        ))
        promoted = await mgr.promote_treatment("test-3")
        assert promoted == "new"
        config = await mgr.get_test("test-3")
        assert config.status == "completed"
        assert config.traffic_split == 1.0

    @pytest.mark.asyncio
    async def test_rollback(self):
        mgr = ABTestManager()
        await mgr.create_test(ABTestConfig(
            test_id="test-4",
            task=ModelTask.INTENT_EXTRACTION,
            control_model="safe",
            treatment_model="risky",
            traffic_split=0.5,
        ))
        await mgr.rollback("test-4")
        config = await mgr.get_test("test-4")
        assert config.status == "rolled_back"
        assert config.traffic_split == 0.0

    @pytest.mark.asyncio
    async def test_update_split(self):
        mgr = ABTestManager()
        await mgr.create_test(ABTestConfig(
            test_id="test-5",
            task=ModelTask.INTENT_EXTRACTION,
            control_model="a",
            treatment_model="b",
            traffic_split=0.05,
        ))
        await mgr.update_split("test-5", 0.25)
        config = await mgr.get_test("test-5")
        assert config.traffic_split == 0.25

    @pytest.mark.asyncio
    async def test_list_active(self):
        mgr = ABTestManager()
        await mgr.create_test(ABTestConfig(
            test_id="active", task=ModelTask.INTENT_EXTRACTION,
            control_model="a", treatment_model="b",
        ))
        active = await mgr.list_active_tests()
        assert len(active) == 1
        assert active[0].test_id == "active"
