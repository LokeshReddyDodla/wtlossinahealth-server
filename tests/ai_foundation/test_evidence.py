"""Tests for evidence & citation layer — summary building, formatting, and edge cases."""

from __future__ import annotations

from unittest.mock import MagicMock

from lib.ai_foundation.agents.health_query.evidence import (
    EvidenceItem,
    InvestigationSummary,
    build_summary,
    build_summary_from_findings,
    compute_coverage_confidence,
    detect_conflicts,
    extract_evidence_from_fallback,
    extract_evidence_from_tool_round,
    format_coverage_note,
    format_data_gaps,
    format_patient,
    format_provider,
    _parse_record_count,
)


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_tool_call(tc_id: str, name: str, args: dict) -> MagicMock:
    tc = MagicMock()
    tc.id = tc_id
    tc.function_name = name
    tc.arguments = args
    return tc


def _make_response(tool_calls: list) -> MagicMock:
    resp = MagicMock()
    resp.tool_calls = tool_calls
    return resp


def _make_tool_msg(tc_id: str, content: str) -> dict:
    return {"role": "tool", "tool_call_id": tc_id, "content": content}


def _make_findings(domain: str, data_gathered: list[str], tool_calls_used: int = 1):
    """Create a mock SpecialistFindings."""
    from dataclasses import dataclass, field

    @dataclass
    class MockFindings:
        domain: str
        findings: str = ""
        tool_calls_used: int = 0
        data_gathered: list[str] = field(default_factory=list)
        cost: float = 0.0

    return MockFindings(domain=domain, data_gathered=data_gathered, tool_calls_used=tool_calls_used)


# ── Test: Record count parsing ───────────────────────────────────────────


class TestRecordCountParsing:
    def test_standard_entries_pattern(self):
        text = "MEAL (5 entries):\n  - date: 2026-03-25, calories: 450"
        assert _parse_record_count(text) == 5

    def test_multiple_entry_sections(self):
        text = "MEAL (3 entries):\n  - ...\n\nCGM_RANGE (7 entries):\n  - ..."
        assert _parse_record_count(text) == 10

    def test_baseline_days_entries_pattern(self):
        text = "Baseline (30 days, 12 entries):\n  - ..."
        assert _parse_record_count(text) == 12

    def test_timeline_pattern(self):
        text = "Timeline for 2026-03-25:\n  08:00 [meal] breakfast\n  12:00 [meal] lunch\n  14:30 [cgm_range_stats] reading"
        assert _parse_record_count(text) == 3

    def test_find_patterns_matches_pattern(self):
        text = "Pattern search: 'glucose spikes' (7 matches):\n  - [cgm_range_stats] ..."
        assert _parse_record_count(text) == 7

    def test_no_parseable_count(self):
        text = "Some unstructured text without entry patterns"
        assert _parse_record_count(text) is None

    def test_no_data_not_parsed(self):
        # NO_DATA results should be detected before calling _parse_record_count
        text = "[NO_DATA] No meal data found for the specified period."
        # Still returns None since no entries pattern
        assert _parse_record_count(text) is None


# ── Test: Extract from tool round ────────────────────────────────────────


class TestExtractFromToolRound:
    def test_single_tool_with_data(self):
        tc = _make_tool_call("tc1", "look_up", {"data_types": ["meal"], "date_start": "2026-03-25", "date_end": "2026-03-27"})
        resp = _make_response([tc])
        msgs = [_make_tool_msg("tc1", "MEAL (5 entries):\n  - date: 2026-03-25")]

        items = extract_evidence_from_tool_round(resp, msgs)
        assert len(items) == 1
        assert items[0].tool == "look_up"
        assert items[0].data_types == ["meal"]
        assert items[0].had_data is True
        assert items[0].record_count == 5
        assert "Mar 25" in items[0].date_range

    def test_no_data_result(self):
        tc = _make_tool_call("tc1", "look_up", {"data_types": ["sleep"]})
        resp = _make_response([tc])
        msgs = [_make_tool_msg("tc1", "[NO_DATA] No sleep data found for the specified period.")]

        items = extract_evidence_from_tool_round(resp, msgs)
        assert len(items) == 1
        assert items[0].had_data is False
        assert items[0].record_count == 0

    def test_multiple_tools_in_round(self):
        tc1 = _make_tool_call("tc1", "look_up", {"data_types": ["meal"]})
        tc2 = _make_tool_call("tc2", "look_up", {"data_types": ["vital"]})
        resp = _make_response([tc1, tc2])
        msgs = [
            _make_tool_msg("tc1", "MEAL (3 entries):\n  - ..."),
            _make_tool_msg("tc2", "[NO_DATA] No vital data found."),
        ]

        items = extract_evidence_from_tool_round(resp, msgs)
        assert len(items) == 2
        assert items[0].had_data is True
        assert items[1].had_data is False

    def test_compare_baseline(self):
        tc = _make_tool_call("tc1", "compare_baseline", {"data_types": ["cgm_range_stats"], "days": 14})
        resp = _make_response([tc])
        msgs = [_make_tool_msg("tc1", "Baseline (14 days, 8 entries):\n  - ...")]

        items = extract_evidence_from_tool_round(resp, msgs)
        assert items[0].date_range == "last 14 days"
        assert items[0].record_count == 8


# ── Test: Extract from fallback ──────────────────────────────────────────


class TestExtractFromFallback:
    def test_fallback_with_data(self):
        item = extract_evidence_from_fallback(
            "look_up",
            {"data_types": ["meal", "cgm_range_stats"], "limit": 15},
            "MEAL (4 entries):\n  - ...\n\nCGM RANGE (6 entries):\n  - ...",
        )
        assert item.had_data is True
        assert item.record_count == 10
        assert item.data_types == ["meal", "cgm_range_stats"]

    def test_fallback_no_data(self):
        item = extract_evidence_from_fallback(
            "look_up",
            {"data_types": ["sleep"]},
            "[NO_DATA] No sleep data found for the specified period.",
        )
        assert item.had_data is False
        assert item.record_count == 0


# ── Test: Build summary — dedup + aggregation ────────────────────────────


class TestBuildSummary:
    def test_deduplicates_same_type_and_range(self):
        items = [
            EvidenceItem(tool="look_up", data_types=["meal"], date_range="Mar 25–27", record_count=3, had_data=True),
            EvidenceItem(tool="look_up", data_types=["meal"], date_range="Mar 25–27", record_count=2, had_data=True),
        ]
        summary = build_summary(items)
        assert len(summary.items) == 1
        assert summary.items[0].record_count == 5

    def test_domains_with_and_without_data(self):
        items = [
            EvidenceItem(tool="look_up", data_types=["meal"], date_range="", record_count=3, had_data=True),
            EvidenceItem(tool="look_up", data_types=["sleep"], date_range="", record_count=0, had_data=False),
        ]
        summary = build_summary(items)
        assert "meal" in summary.domains_with_data
        assert "sleep" in summary.domains_without_data

    def test_total_records(self):
        items = [
            EvidenceItem(tool="look_up", data_types=["meal"], date_range="", record_count=5, had_data=True),
            EvidenceItem(tool="look_up", data_types=["vital"], date_range="", record_count=3, had_data=True),
        ]
        summary = build_summary(items)
        assert summary.total_records == 8

    def test_empty_ledger(self):
        summary = build_summary([])
        assert summary.items == []
        assert summary.total_records is None


# ── Test: All NO_DATA ────────────────────────────────────────────────────


class TestAllNoData:
    def test_patient_format(self):
        items = [
            EvidenceItem(tool="look_up", data_types=["meal"], date_range="", record_count=0, had_data=False),
            EvidenceItem(tool="look_up", data_types=["sleep"], date_range="", record_count=0, had_data=False),
        ]
        summary = build_summary(items)
        text = format_patient(summary)
        assert "No health data was found" in text

    def test_provider_format(self):
        items = [
            EvidenceItem(tool="look_up", data_types=["meal"], date_range="", record_count=0, had_data=False),
        ]
        summary = build_summary(items)
        text = format_provider(summary)
        assert "No health data was found" in text


# ── Test: Role-aware formatting ──────────────────────────────────────────


class TestFormatPatient:
    def test_single_domain(self):
        items = [EvidenceItem(tool="look_up", data_types=["meal"], date_range="Mar 25–27", record_count=5, had_data=True)]
        summary = build_summary(items)
        text = format_patient(summary)
        assert "Based on" in text
        assert "meals" in text
        assert "Mar 25–27" in text

    def test_with_gap(self):
        items = [
            EvidenceItem(tool="look_up", data_types=["meal"], date_range="", record_count=3, had_data=True),
            EvidenceItem(tool="look_up", data_types=["sleep"], date_range="", record_count=0, had_data=False),
        ]
        summary = build_summary(items)
        text = format_patient(summary)
        assert "sleep" in text.lower()
        assert "not available" in text.lower() or "no sleep" in text.lower()

    def test_empty_summary(self):
        summary = InvestigationSummary()
        assert format_patient(summary) == ""


class TestFormatProvider:
    def test_structured_sources(self):
        items = [
            EvidenceItem(tool="look_up", data_types=["cgm_range_stats"], date_range="Mar 25–28", record_count=12, had_data=True),
            EvidenceItem(tool="look_up", data_types=["meal"], date_range="Mar 25–27", record_count=5, had_data=True),
        ]
        summary = build_summary(items)
        text = format_provider(summary)
        assert "**Sources:**" in text
        assert "CGM" in text
        assert "meal" in text.lower()

    def test_with_gaps(self):
        items = [
            EvidenceItem(tool="look_up", data_types=["meal"], date_range="", record_count=3, had_data=True),
            EvidenceItem(tool="look_up", data_types=["sleep"], date_range="", record_count=0, had_data=False),
            EvidenceItem(tool="look_up", data_types=["vital"], date_range="", record_count=0, had_data=False),
        ]
        summary = build_summary(items)
        text = format_provider(summary)
        assert "Gaps:" in text
        assert "sleep" in text
        assert "vitals" in text

    def test_empty_summary(self):
        summary = InvestigationSummary()
        assert format_provider(summary) == ""


# ── Test: Build from specialist findings ─────────────────────────────────


class TestBuildFromFindings:
    def test_findings_with_data(self):
        findings = [
            _make_findings("glucose", ["CGM RANGE (8 entries):\n  - ..."]),
            _make_findings("nutrition", ["MEAL (3 entries):\n  - ..."]),
        ]
        summary = build_summary_from_findings(findings)
        assert len(summary.domains_with_data) == 2
        assert summary.total_records == 11

    def test_findings_with_analysis_text_only(self):
        """Specialist that returned only LLM analysis text, no tool results — should not claim data."""
        findings = [
            _make_findings("glucose", ["The patient shows good glucose control overall."]),
        ]
        summary = build_summary_from_findings(findings)
        assert len(summary.domains_with_data) == 0
        assert summary.total_records is None

    def test_findings_mixed(self):
        findings = [
            _make_findings("glucose", ["CGM RANGE (8 entries):\n  - ..."]),
            _make_findings("sleep", ["[NO_DATA] No sleep data found."]),
        ]
        summary = build_summary_from_findings(findings)
        assert "sleep" in summary.domains_without_data


# ── Test: Missing args / graceful fallback ───────────────────────────────


class TestGracefulFallback:
    def test_missing_date_args(self):
        tc = _make_tool_call("tc1", "look_up", {"data_types": ["meal"]})
        resp = _make_response([tc])
        msgs = [_make_tool_msg("tc1", "MEAL (3 entries):\n  - ...")]

        items = extract_evidence_from_tool_round(resp, msgs)
        assert items[0].date_range == ""  # no crash, empty string

    def test_missing_tool_call_id(self):
        """Messages without matching tool_call_id are skipped."""
        tc = _make_tool_call("tc1", "look_up", {"data_types": ["meal"]})
        resp = _make_response([tc])
        msgs = [{"role": "tool", "tool_call_id": "unknown", "content": "data"}]

        items = extract_evidence_from_tool_round(resp, msgs)
        assert len(items) == 0

    def test_data_types_as_string(self):
        """Handle edge case where data_types is a string instead of list."""
        item = extract_evidence_from_fallback("look_up", {"data_types": "meal"}, "MEAL (2 entries):\n  - ...")
        assert item.data_types == ["meal"]

    def test_investigate_day_no_data_types_in_args(self):
        """investigate_day has no data_types arg — parse from result text."""
        tc = _make_tool_call("tc1", "investigate_day", {"date": "2026-03-25"})
        resp = _make_response([tc])
        msgs = [_make_tool_msg("tc1", "Timeline for 2026-03-25:\n  08:00 [meal] breakfast\n  14:30 [cgm_range_stats] reading")]

        items = extract_evidence_from_tool_round(resp, msgs)
        assert len(items) == 1
        assert "meal" in items[0].data_types
        assert "cgm_range_stats" in items[0].data_types
        assert items[0].date_range == "2026-03-25"

    def test_find_patterns_no_data_types_in_args(self):
        """find_patterns has no data_types arg — parse from result text using [type] tags."""
        tc = _make_tool_call("tc1", "find_patterns", {"query": "glucose spikes", "days_back": 14})
        resp = _make_response([tc])
        # find_patterns output uses [data_type] tags per line
        msgs = [_make_tool_msg("tc1", "Pattern search: 'glucose spikes' (5 matches):\n  - [cgm_range_stats] avg: 200\n  - [meal] carbs: 80")]

        items = extract_evidence_from_tool_round(resp, msgs)
        assert len(items) == 1
        assert "cgm_range_stats" in items[0].data_types
        assert "meal" in items[0].data_types
        assert items[0].date_range == "last 14 days"


# ── Test: Coverage confidence scoring ────────────────────────────────────


class TestCoverageConfidence:
    def test_full_coverage_high_score(self):
        items = [
            EvidenceItem(tool="look_up", data_types=["meal"], date_range="Mar 25–27", record_count=10, had_data=True),
            EvidenceItem(tool="look_up", data_types=["cgm_range_stats"], date_range="Mar 25–27", record_count=15, had_data=True),
        ]
        summary = build_summary(items)
        assert compute_coverage_confidence(summary) >= 0.9

    def test_missing_domains_reduces_score(self):
        items = [
            EvidenceItem(tool="look_up", data_types=["meal"], date_range="Mar 25–27", record_count=5, had_data=True),
            EvidenceItem(tool="look_up", data_types=["sleep"], date_range="", record_count=0, had_data=False),
            EvidenceItem(tool="look_up", data_types=["vital"], date_range="", record_count=0, had_data=False),
        ]
        summary = build_summary(items)
        assert compute_coverage_confidence(summary) < 0.8

    def test_thin_records_reduces_score(self):
        items = [EvidenceItem(tool="look_up", data_types=["meal"], date_range="Mar 25", record_count=2, had_data=True)]
        summary = build_summary(items)
        assert compute_coverage_confidence(summary) < 0.9

    def test_all_no_data_floor(self):
        items = [EvidenceItem(tool="look_up", data_types=["meal"], date_range="", record_count=0, had_data=False)]
        summary = build_summary(items)
        assert compute_coverage_confidence(summary) == 0.1

    def test_empty_summary_floor(self):
        assert compute_coverage_confidence(InvestigationSummary()) == 0.1

    def test_no_date_coverage_penalty(self):
        items = [EvidenceItem(tool="look_up", data_types=["meal"], date_range="", record_count=5, had_data=True)]
        summary = build_summary(items)
        assert compute_coverage_confidence(summary) <= 0.9

    def test_score_never_below_floor(self):
        items = [
            EvidenceItem(tool="look_up", data_types=["meal"], date_range="", record_count=0, had_data=False),
            EvidenceItem(tool="look_up", data_types=["sleep"], date_range="", record_count=0, had_data=False),
            EvidenceItem(tool="look_up", data_types=["vital"], date_range="", record_count=0, had_data=False),
            EvidenceItem(tool="look_up", data_types=["cgm_range_stats"], date_range="", record_count=0, had_data=False),
        ]
        summary = build_summary(items)
        assert compute_coverage_confidence(summary) == 0.1


class TestCoverageNote:
    def test_good_coverage_empty_note(self):
        items = [EvidenceItem(tool="look_up", data_types=["meal"], date_range="Mar 25–27", record_count=10, had_data=True)]
        summary = build_summary(items)
        assert format_coverage_note(summary) == ""

    def test_thin_records_note(self):
        items = [EvidenceItem(tool="look_up", data_types=["meal"], date_range="Mar 25", record_count=2, had_data=True)]
        summary = build_summary(items)
        note = format_coverage_note(summary)
        assert "Limited data" in note
        assert "2 records" in note

    def test_missing_domains_note(self):
        items = [
            EvidenceItem(tool="look_up", data_types=["meal"], date_range="", record_count=10, had_data=True),
            EvidenceItem(tool="look_up", data_types=["sleep"], date_range="", record_count=0, had_data=False),
        ]
        summary = build_summary(items)
        note = format_coverage_note(summary)
        assert "Partial coverage" in note
        assert "sleep" in note.lower()

    def test_combined_thin_and_missing(self):
        items = [
            EvidenceItem(tool="look_up", data_types=["meal"], date_range="", record_count=2, had_data=True),
            EvidenceItem(tool="look_up", data_types=["sleep"], date_range="", record_count=0, had_data=False),
        ]
        summary = build_summary(items)
        note = format_coverage_note(summary)
        assert "Limited data" in note
        assert "Partial coverage" in note

    def test_empty_summary(self):
        assert format_coverage_note(InvestigationSummary()) == ""


class TestDataGaps:
    def test_no_gaps(self):
        items = [EvidenceItem(tool="look_up", data_types=["meal"], date_range="", record_count=5, had_data=True)]
        summary = build_summary(items)
        assert format_data_gaps(summary) is None

    def test_gaps_use_human_labels(self):
        items = [
            EvidenceItem(tool="look_up", data_types=["meal"], date_range="", record_count=5, had_data=True),
            EvidenceItem(tool="look_up", data_types=["cgm_range_stats"], date_range="", record_count=0, had_data=False),
        ]
        summary = build_summary(items)
        gaps = format_data_gaps(summary)
        assert gaps is not None
        assert "glucose readings" in gaps  # human label, not "cgm"


# ── Test: Conflict detection ─────────────────────────────────────────────


class TestConflictDetection:
    def test_data_exists_contradiction(self):
        """One tool found NO_DATA, another found data for same domain."""
        items = [
            EvidenceItem(tool="look_up", data_types=["meal"], date_range="Mar 25–27", record_count=0, had_data=False),
            EvidenceItem(tool="investigate_day", data_types=["meal"], date_range="Mar 26", record_count=3, had_data=True),
        ]
        conflicts = detect_conflicts(items)
        assert len(conflicts) == 1
        assert "conflicting" in conflicts[0].lower() or "availability" in conflicts[0].lower()

    def test_count_discrepancy(self):
        """Same domain with >3x record count difference between tools."""
        items = [
            EvidenceItem(tool="look_up", data_types=["cgm_range_stats"], date_range="Mar 25–27", record_count=2, had_data=True),
            EvidenceItem(tool="compare_baseline", data_types=["cgm_range_stats"], date_range="last 30 days", record_count=25, had_data=True),
        ]
        conflicts = detect_conflicts(items)
        assert len(conflicts) == 1
        assert "discrepancy" in conflicts[0].lower()

    def test_no_conflict_consistent_data(self):
        """All tools agree — no conflicts."""
        items = [
            EvidenceItem(tool="look_up", data_types=["meal"], date_range="Mar 25–27", record_count=5, had_data=True),
            EvidenceItem(tool="look_up", data_types=["cgm_range_stats"], date_range="Mar 25–27", record_count=10, had_data=True),
        ]
        conflicts = detect_conflicts(items)
        assert len(conflicts) == 0

    def test_no_conflict_single_item(self):
        """Single evidence item can't conflict with itself."""
        items = [EvidenceItem(tool="look_up", data_types=["meal"], date_range="Mar 25", record_count=5, had_data=True)]
        assert detect_conflicts(items) == []

    def test_no_conflict_empty(self):
        assert detect_conflicts([]) == []

    def test_small_count_difference_no_conflict(self):
        """2x difference should not trigger (threshold is 3x)."""
        items = [
            EvidenceItem(tool="look_up", data_types=["meal"], date_range="", record_count=5, had_data=True),
            EvidenceItem(tool="compare_baseline", data_types=["meal"], date_range="", record_count=10, had_data=True),
        ]
        conflicts = detect_conflicts(items)
        assert len(conflicts) == 0

    def test_multiple_conflicts(self):
        """Both contradiction types can fire for different domains."""
        items = [
            # Domain 1: data-exists contradiction
            EvidenceItem(tool="look_up", data_types=["meal"], date_range="", record_count=0, had_data=False),
            EvidenceItem(tool="investigate_day", data_types=["meal"], date_range="Mar 25", record_count=2, had_data=True),
            # Domain 2: count discrepancy
            EvidenceItem(tool="look_up", data_types=["cgm_range_stats"], date_range="", record_count=1, had_data=True),
            EvidenceItem(tool="compare_baseline", data_types=["cgm_range_stats"], date_range="", record_count=20, had_data=True),
        ]
        conflicts = detect_conflicts(items)
        assert len(conflicts) == 2
