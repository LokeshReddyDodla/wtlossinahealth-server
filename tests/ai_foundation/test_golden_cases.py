"""Tests for the golden eval dataset — validates structure and coverage."""

import json
from pathlib import Path
from collections import Counter

import pytest

from lib.ai_foundation.eval.schemas import EvalCase, EvalTaskType
from lib.ai_foundation.eval.runners.intent_eval import load_eval_cases

GOLDEN_PATH = Path("lib/ai_foundation/eval/datasets/intent_golden_cases.jsonl")


class TestGoldenDataset:
    def test_file_exists(self):
        assert GOLDEN_PATH.exists()

    def test_loads_all_cases(self):
        cases = load_eval_cases(GOLDEN_PATH)
        assert len(cases) == 50

    def test_all_cases_valid(self):
        cases = load_eval_cases(GOLDEN_PATH)
        for case in cases:
            assert case.case_id.startswith("intent-")
            assert case.task_type == EvalTaskType.INTENT_EXTRACTION
            assert case.input_query.strip()
            assert case.expected_is_ready is not None

    def test_unique_case_ids(self):
        cases = load_eval_cases(GOLDEN_PATH)
        ids = [c.case_id for c in cases]
        assert len(ids) == len(set(ids)), f"Duplicate IDs: {[x for x, c in Counter(ids).items() if c > 1]}"

    def test_coverage_ready_vs_not_ready(self):
        cases = load_eval_cases(GOLDEN_PATH)
        ready = sum(1 for c in cases if c.expected_is_ready)
        not_ready = sum(1 for c in cases if not c.expected_is_ready)
        assert ready >= 35, f"Need at least 35 ready cases, got {ready}"
        assert not_ready >= 5, f"Need at least 5 not-ready cases, got {not_ready}"

    def test_coverage_domains(self):
        """Ensure all major health domains are covered."""
        cases = load_eval_cases(GOLDEN_PATH)
        all_tags = set()
        for c in cases:
            all_tags.update(c.tags)

        required_domains = {"cgm", "meal", "fitness", "sleep", "profile", "documents", "smbg"}
        covered = required_domains & all_tags
        missing = required_domains - all_tags
        assert not missing, f"Missing domain coverage: {missing}"

    def test_coverage_difficulty(self):
        cases = load_eval_cases(GOLDEN_PATH)
        all_tags = set()
        for c in cases:
            all_tags.update(c.tags)

        assert "simple" in all_tags
        assert "medium" in all_tags
        assert "hard" in all_tags

    def test_coverage_patterns(self):
        """Ensure key query patterns are covered."""
        cases = load_eval_cases(GOLDEN_PATH)
        all_tags = set()
        for c in cases:
            all_tags.update(c.tags)

        required_patterns = {
            "date_range",
            "follow_up",
            "clarification_needed",
            "numeric_filter",
            "cross_domain",
            "multi_domain",
        }
        covered = required_patterns & all_tags
        missing = required_patterns - all_tags
        assert not missing, f"Missing pattern coverage: {missing}"

    def test_follow_up_cases_have_context(self):
        cases = load_eval_cases(GOLDEN_PATH)
        follow_ups = [c for c in cases if "follow_up" in c.tags]
        assert len(follow_ups) >= 5, "Need at least 5 follow-up cases"
        for c in follow_ups:
            assert c.conversation_context is not None, (
                f"Follow-up case {c.case_id} must have conversation_context"
            )

    def test_data_types_are_valid_enums(self):
        """Ensure all expected_data_types are valid HealthDataType values."""
        from lib.ai_foundation.agents.health_query.contracts import HealthDataType

        valid_values = {dt.value for dt in HealthDataType}
        cases = load_eval_cases(GOLDEN_PATH)
        for case in cases:
            if case.expected_data_types:
                for dt in case.expected_data_types:
                    assert dt in valid_values, (
                        f"Case {case.case_id}: '{dt}' is not a valid HealthDataType"
                    )

    def test_tag_distribution(self):
        """Print tag distribution for review (not a pass/fail test)."""
        cases = load_eval_cases(GOLDEN_PATH)
        tag_counts = Counter()
        for c in cases:
            tag_counts.update(c.tags)

        # At least check we have diversity
        assert len(tag_counts) >= 15, f"Only {len(tag_counts)} unique tags — need more diversity"
