"""
Provider Triage — ranks patients by health urgency from recent insights.

Pure functions. No I/O, no LLM calls. Takes pre-fetched insights and
patient names, returns ranked list for provider dashboard.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from lib.ai_foundation.agents.proactive_monitor.contracts import SEVERITY_RANK

_URGENT_SEVERITIES = frozenset({"warning", "alert"})


# ── Models ───────────────────────────────────────────────────────────────


class PatientTriage(BaseModel):
    """Single patient's triage summary."""

    patient_id: str
    patient_name: str
    top_severity: str = "none"      # "alert" | "warning" | "attention" | "info" | "none"
    alert_count: int = 0            # WARNING + ALERT in period
    insight_count: int = 0          # total insights in period
    recent_insights: list[dict[str, Any]] = Field(default_factory=list)
    needs_attention: bool = False   # True if any WARNING or ALERT


class ProviderPanelResponse(BaseModel):
    """Response for the provider panel endpoint."""

    total_patients: int
    patients_needing_attention: int
    ranked_patients: list[PatientTriage] = Field(default_factory=list)


# ── Ranking ──────────────────────────────────────────────────────────────


def rank_patients(
    *,
    patient_ids: list[str],
    patient_names: dict[str, str],
    insights_by_patient: dict[str, list[dict]],
) -> list[PatientTriage]:
    """Rank patients by health urgency from recent insights.

    Sort order:
    1. Max severity (alert > warning > attention > info > none)
    2. Alert count (WARNING + ALERT)
    3. Most recent insight time (newest first)
    4. Patients with no insights sort last

    Returns all patients, including those with no insights.
    """
    triage_list: list[PatientTriage] = []

    for pid in patient_ids:
        name = patient_names.get(pid, f"Patient ({pid[:8]})")
        insights = insights_by_patient.get(pid, [])

        if not insights:
            triage_list.append(PatientTriage(
                patient_id=pid,
                patient_name=name,
            ))
            continue

        # Compute severity metrics
        max_severity = "none"
        max_rank = 0
        alert_count = 0

        for ins in insights:
            sev = ins.get("severity", "info")
            rank = SEVERITY_RANK.get(sev, 0)
            if rank > max_rank:
                max_rank = rank
                max_severity = sev
            if sev in _URGENT_SEVERITIES:
                alert_count += 1

        # Clean insights for response (remove internal fields, normalize timestamps)
        clean_insights = []
        for ins in insights:
            created_at = ins.get("created_at")
            # Normalize to ISO string for JSON serialization
            if isinstance(created_at, datetime):
                created_at = created_at.isoformat()
            elif isinstance(created_at, str) and created_at.endswith("Z"):
                created_at = created_at[:-1] + "+00:00"
            clean_insights.append({
                "insight_id": ins.get("insight_id", ""),
                "category": ins.get("category", ""),
                "severity": ins.get("severity", "info"),
                "title": ins.get("title", ""),
                "message": ins.get("message", ""),
                "suggested_query": ins.get("suggested_query"),
                "created_at": created_at,
            })

        triage_list.append(PatientTriage(
            patient_id=pid,
            patient_name=name,
            top_severity=max_severity,
            alert_count=alert_count,
            insight_count=len(insights),
            recent_insights=clean_insights,
            needs_attention=alert_count > 0,
        ))

    # Sort: highest severity first, then by alert count, then by recency
    def _sort_key(t: PatientTriage) -> tuple:
        most_recent_ts = 0.0
        if t.recent_insights:
            for ins in t.recent_insights:
                ts = ins.get("created_at")
                # Handle both datetime objects and ISO strings from MongoDB
                if isinstance(ts, datetime):
                    val = ts.timestamp()
                elif isinstance(ts, str):
                    try:
                        # Handle MongoDB "Z" suffix and timezone-aware strings
                        if ts.endswith("Z"):
                            ts = ts[:-1] + "+00:00"
                        val = datetime.fromisoformat(ts).timestamp()
                    except (ValueError, TypeError):
                        val = 0.0
                else:
                    val = 0.0
                if val > most_recent_ts:
                    most_recent_ts = val
        return (
            -SEVERITY_RANK.get(t.top_severity, 0),
            -t.alert_count,
            -most_recent_ts,
        )

    triage_list.sort(key=_sort_key)
    return triage_list


def build_panel_response(
    *,
    total_patients: int,
    ranked_patients: list[PatientTriage],
    limit: int = 20,
) -> ProviderPanelResponse:
    """Build the final panel response with summary stats."""
    attention_count = sum(1 for p in ranked_patients if p.needs_attention)
    return ProviderPanelResponse(
        total_patients=total_patients,
        patients_needing_attention=attention_count,
        ranked_patients=ranked_patients[:limit],
    )
