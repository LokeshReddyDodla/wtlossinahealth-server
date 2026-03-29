"""Tests for result ranking utilities — sorting, truncation, and tool formatting integration."""

from __future__ import annotations

from lib.ai_foundation.agents.health_query.result_ranking import (
    _extract_time_key,
    cap_at_record_boundaries,
    sort_by_time,
)
from lib.ai_foundation.retrieval.base import RetrievalResult


# ── Helpers ──────────────────────────────────────────────────────────────


def _result(payload: dict, data_type: str = "meal") -> RetrievalResult:
    return RetrievalResult(payload=payload, source="qdrant_filtered", score=None, data_type=data_type)


# ── Test: sort_by_time ───────────────────────────────────────────────────


class TestSortByTime:
    def test_descending_by_start_time(self):
        results = [
            _result({"start_time": 1000}),
            _result({"start_time": 3000}),
            _result({"start_time": 2000}),
        ]
        sorted_r = sort_by_time(results)
        assert [r.payload["start_time"] for r in sorted_r] == [3000, 2000, 1000]

    def test_ascending_by_start_time(self):
        results = [
            _result({"start_time": 3000}),
            _result({"start_time": 1000}),
            _result({"start_time": 2000}),
        ]
        sorted_r = sort_by_time(results, ascending=True)
        assert [r.payload["start_time"] for r in sorted_r] == [1000, 2000, 3000]

    def test_fallback_to_date_field(self):
        results = [
            _result({"date": "2026-03-25"}),
            _result({"date": "2026-03-27"}),
            _result({"date": "2026-03-26"}),
        ]
        sorted_r = sort_by_time(results)
        assert [r.payload["date"] for r in sorted_r] == ["2026-03-27", "2026-03-26", "2026-03-25"]

    def test_fallback_to_date_plus_time(self):
        results = [
            _result({"date": "2026-03-25", "time": "08:30"}),
            _result({"date": "2026-03-25", "time": "14:00"}),
            _result({"date": "2026-03-25", "time": "06:00"}),
        ]
        sorted_r = sort_by_time(results, ascending=True)
        times = [r.payload["time"] for r in sorted_r]
        assert times == ["06:00", "08:30", "14:00"]

    def test_time_only_ranks_below_full_datetime(self):
        results = [
            _result({"time": "10:00"}),  # time only — low epoch
            _result({"date": "2026-03-25", "time": "08:00"}),  # full datetime — real epoch
        ]
        sorted_r = sort_by_time(results)  # descending
        # Full datetime should come first (higher epoch)
        assert "date" in sorted_r[0].payload
        assert "date" not in sorted_r[1].payload

    def test_missing_all_time_fields_sorts_last(self):
        results = [
            _result({"start_time": 5000}),
            _result({"name": "no time fields"}),
            _result({"start_time": 3000}),
        ]
        sorted_r = sort_by_time(results)
        assert sorted_r[-1].payload.get("name") == "no time fields"

    def test_invalid_start_time_sorts_last(self):
        results = [
            _result({"start_time": "not_a_number"}),
            _result({"start_time": 1000}),
        ]
        sorted_r = sort_by_time(results)
        assert sorted_r[0].payload["start_time"] == 1000
        assert sorted_r[1].payload["start_time"] == "not_a_number"

    def test_empty_list(self):
        assert sort_by_time([]) == []

    def test_base_date_anchors_time_only(self):
        """Time-only records anchored to base_date should sort correctly with full datetimes."""
        results = [
            _result({"time": "23:00"}),  # time only
            _result({"date": "2026-03-25", "time": "08:00"}),  # full datetime
        ]
        sorted_r = sort_by_time(results, ascending=True, base_date="2026-03-25")
        # 08:00 should come before 23:00 on the same day
        assert sorted_r[0].payload["time"] == "08:00"
        assert sorted_r[1].payload["time"] == "23:00"


# ── Test: cap_at_record_boundaries ───────────────────────────────────────


class TestCapAtRecordBoundaries:
    def test_under_limit_no_change(self):
        text = "MEAL (3 entries):\n  - meal 1\n  - meal 2\n  - meal 3"
        assert cap_at_record_boundaries(text, 500) == text

    def test_truncates_at_line_boundary(self):
        lines = ["MEAL (10 entries):"] + [f"  - meal {i} with extra data padding" for i in range(10)]
        text = "\n".join(lines)
        result = cap_at_record_boundaries(text, 120)
        assert "MEAL (10 entries):" in result
        assert "meal 0" in result  # at least first record kept
        assert "more lines" in result
        assert len(result) <= 120

    def test_preserves_header(self):
        text = "MEAL (5 entries):\n  - record1\n  - record2\n  - record3\n  - record4\n  - record5"
        result = cap_at_record_boundaries(text, 40)
        assert result.startswith("MEAL (5 entries):")

    def test_shows_omitted_count(self):
        lines = ["Header:"] + [f"  - record {i}" for i in range(20)]
        text = "\n".join(lines)
        result = cap_at_record_boundaries(text, 100)
        assert "more lines" in result

    def test_exact_fit(self):
        text = "line1\nline2"
        result = cap_at_record_boundaries(text, len(text))
        assert result == text

    def test_empty_text(self):
        assert cap_at_record_boundaries("", 100) == ""

    def test_never_exceeds_max_chars(self):
        """Result must never exceed max_chars, even with single long line."""
        text = "x" * 5000
        result = cap_at_record_boundaries(text, 100)
        assert len(result) <= 100

    def test_long_first_line_with_records(self):
        """Long header + records should still respect budget."""
        text = "H" * 300 + "\n  - record 1\n  - record 2"
        result = cap_at_record_boundaries(text, 200)
        assert len(result) <= 200


# ── Test: _extract_time_key ──────────────────────────────────────────────


class TestExtractTimeKey:
    def test_start_time_epoch(self):
        assert _extract_time_key({"start_time": 1711353600000}) == 1711353600000.0

    def test_date_string(self):
        key = _extract_time_key({"date": "2026-03-25"})
        assert key > 0

    def test_date_plus_time(self):
        key_early = _extract_time_key({"date": "2026-03-25", "time": "06:00"})
        key_late = _extract_time_key({"date": "2026-03-25", "time": "18:00"})
        assert key_late > key_early

    def test_time_only_low_value(self):
        key = _extract_time_key({"time": "10:30"})
        assert 0 < key < 100_000  # much lower than any real epoch

    def test_no_time_fields(self):
        assert _extract_time_key({"name": "profile"}) == 0.0

    def test_invalid_date(self):
        assert _extract_time_key({"date": "not-a-date"}) == 0.0


# ── Integration: _format_results with sorted data ────────────────────────


class TestFormatResultsIntegration:
    def test_requested_types_order_preserved(self):
        """Sections should follow requested_types order, not insertion order."""
        from unittest.mock import MagicMock
        from lib.ai_foundation.agents.health_query.tools import ToolExecutor

        # Create mock executor to access _format_results
        executor = MagicMock(spec=ToolExecutor)
        executor._format_results = ToolExecutor._format_results.__get__(executor)

        results = [
            _result({"start_time": 1000, "value": "glucose1"}, data_type="cgm_range_stats"),
            _result({"start_time": 2000, "calories": 500}, data_type="meal"),
            _result({"start_time": 3000, "value": "glucose2"}, data_type="cgm_range_stats"),
        ]

        text = executor._format_results(results, requested_types=["meal", "cgm_range_stats"])
        lines = text.split("\n")

        # Find section header positions
        meal_pos = next(i for i, l in enumerate(lines) if "MEAL" in l)
        cgm_pos = next(i for i, l in enumerate(lines) if "CGM" in l)
        assert meal_pos < cgm_pos, "meal section should come before cgm (requested order)"

    def test_records_sorted_within_groups(self):
        """Most recent records should appear first within each group."""
        from unittest.mock import MagicMock
        from lib.ai_foundation.agents.health_query.tools import ToolExecutor

        executor = MagicMock(spec=ToolExecutor)
        executor._format_results = ToolExecutor._format_results.__get__(executor)

        results = [
            _result({"start_time": 1000, "calories": 100}, data_type="meal"),
            _result({"start_time": 3000, "calories": 300}, data_type="meal"),
            _result({"start_time": 2000, "calories": 200}, data_type="meal"),
        ]

        text = executor._format_results(results)
        # First record line should have calories: 300 (most recent)
        record_lines = [l for l in text.split("\n") if l.strip().startswith("- ")]
        assert "300" in record_lines[0]
