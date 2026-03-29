"""Tests for provider triage ranking — severity ordering, tie-breaking, edge cases."""

from __future__ import annotations

from datetime import datetime, timedelta

from lib.ai_foundation.agents.health_query.triage import (
    PatientTriage,
    ProviderPanelResponse,
    build_panel_response,
    rank_patients,
)


# ── Helpers ──────────────────────────────────────────────────────────────


def _insight(severity: str = "info", category: str = "general", hours_ago: int = 1) -> dict:
    return {
        "insight_id": f"ins_{severity}_{hours_ago}",
        "category": category,
        "severity": severity,
        "title": f"Test {severity}",
        "message": f"Test message ({severity})",
        "suggested_query": None,
        "created_at": datetime.utcnow() - timedelta(hours=hours_ago),
    }


# ── Test: Severity ranking ──────────────────────────────────────────────


class TestSeverityRanking:
    def test_alert_ranks_first(self):
        ranked = rank_patients(
            patient_ids=["p1", "p2", "p3"],
            patient_names={"p1": "Alice", "p2": "Bob", "p3": "Carol"},
            insights_by_patient={
                "p1": [_insight("info")],
                "p2": [_insight("alert")],
                "p3": [_insight("warning")],
            },
        )
        assert ranked[0].patient_id == "p2"  # alert
        assert ranked[1].patient_id == "p3"  # warning
        assert ranked[2].patient_id == "p1"  # info

    def test_no_insights_ranks_last(self):
        ranked = rank_patients(
            patient_ids=["p1", "p2"],
            patient_names={"p1": "Alice", "p2": "Bob"},
            insights_by_patient={
                "p1": [_insight("attention")],
                # p2 has no insights
            },
        )
        assert ranked[0].patient_id == "p1"
        assert ranked[1].patient_id == "p2"
        assert ranked[1].top_severity == "none"
        assert ranked[1].needs_attention is False


# ── Test: Tie-breaking ──────────────────────────────────────────────────


class TestTieBreaking:
    def test_same_severity_breaks_by_alert_count(self):
        ranked = rank_patients(
            patient_ids=["p1", "p2"],
            patient_names={"p1": "Alice", "p2": "Bob"},
            insights_by_patient={
                "p1": [_insight("warning")],
                "p2": [_insight("warning"), _insight("alert")],
            },
        )
        assert ranked[0].patient_id == "p2"  # 2 alerts vs 1

    def test_same_severity_and_count_breaks_by_recency(self):
        ranked = rank_patients(
            patient_ids=["p1", "p2"],
            patient_names={"p1": "Alice", "p2": "Bob"},
            insights_by_patient={
                "p1": [_insight("warning", hours_ago=24)],
                "p2": [_insight("warning", hours_ago=1)],
            },
        )
        assert ranked[0].patient_id == "p2"  # more recent


# ── Test: Metrics computation ────────────────────────────────────────────


class TestMetrics:
    def test_alert_count(self):
        ranked = rank_patients(
            patient_ids=["p1"],
            patient_names={"p1": "Alice"},
            insights_by_patient={
                "p1": [_insight("alert"), _insight("warning"), _insight("info")],
            },
        )
        assert ranked[0].alert_count == 2  # alert + warning
        assert ranked[0].insight_count == 3
        assert ranked[0].needs_attention is True

    def test_info_only_no_attention(self):
        ranked = rank_patients(
            patient_ids=["p1"],
            patient_names={"p1": "Alice"},
            insights_by_patient={
                "p1": [_insight("info"), _insight("attention")],
            },
        )
        assert ranked[0].needs_attention is False
        assert ranked[0].alert_count == 0

    def test_patient_name_fallback(self):
        ranked = rank_patients(
            patient_ids=["p1"],
            patient_names={},  # no names resolved
            insights_by_patient={},
        )
        assert "Patient" in ranked[0].patient_name


# ── Test: Panel response ─────────────────────────────────────────────────


class TestPanelResponse:
    def test_builds_response_with_limit(self):
        ranked = rank_patients(
            patient_ids=["p1", "p2", "p3"],
            patient_names={"p1": "A", "p2": "B", "p3": "C"},
            insights_by_patient={
                "p1": [_insight("alert")],
                "p2": [_insight("info")],
            },
        )
        response = build_panel_response(
            total_patients=3,
            ranked_patients=ranked,
            limit=2,
        )
        assert response.total_patients == 3
        assert response.patients_needing_attention == 1
        assert len(response.ranked_patients) == 2

    def test_empty_panel(self):
        response = build_panel_response(
            total_patients=0,
            ranked_patients=[],
        )
        assert response.total_patients == 0
        assert response.patients_needing_attention == 0
        assert response.ranked_patients == []

    def test_all_need_attention(self):
        ranked = rank_patients(
            patient_ids=["p1", "p2"],
            patient_names={"p1": "A", "p2": "B"},
            insights_by_patient={
                "p1": [_insight("alert")],
                "p2": [_insight("warning")],
            },
        )
        response = build_panel_response(total_patients=2, ranked_patients=ranked)
        assert response.patients_needing_attention == 2
