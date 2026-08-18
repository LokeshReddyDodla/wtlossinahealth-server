"""Deterministic triage classification — a pure function over PanelInputs."""

from __future__ import annotations

from lib.schemas.patient_panel_signal import (
    PanelAssessment,
    PanelInputs,
    ReasonSeverity,
    Triage,
)
from lib.services.patient_panel.thresholds import for_patient

_P_AT_RISK = 0
_P_WATCH = 20
_P_DATA_GAP = 30
_P_NOT_STARTED = 40
_P_RESPONDING = 50


def _pct(v: float) -> str:
    return f"{v:g}%"


def _num(v: float) -> str:
    return f"{v:g}"


def classify(inp: PanelInputs) -> Triage:
    t = for_patient(inp.is_pregnant)

    if not inp.has_any_data:
        return Triage(
            assessment=PanelAssessment.NOT_STARTED,
            reason="Not monitoring yet — needs onboarding",
            severity=ReasonSeverity.INFO,
            priority=_P_NOT_STARTED,
        )

    if inp.glucose_sync_stale:
        tail = f" · {inp.glucose_sync_stale_days}d" if inp.glucose_sync_stale_days else ""
        return Triage(
            assessment=PanelAssessment.DATA_GAP,
            reason=f"No recent CGM{tail}",
            severity=ReasonSeverity.WATCH,
            priority=_P_DATA_GAP,
        )

    if inp.nocturnal_below_70_pct is not None and inp.nocturnal_below_70_pct >= t.nocturnal_hypo_pct:
        return _at_risk(f"Nocturnal hypo {_pct(inp.nocturnal_below_70_pct)}")
    if inp.below_54_pct is not None and inp.below_54_pct >= t.very_low_pct:
        return _at_risk(f"Severe lows · {_pct(inp.below_54_pct)} <54 mg/dL")
    if inp.hypo_events is not None and inp.hypo_events >= t.frequent_low_events:
        return _at_risk(f"Frequent lows · {inp.hypo_events} events")

    if inp.a1c is not None and inp.a1c >= t.a1c_high:
        return _at_risk(f"A1c {_pct(inp.a1c)}, uncontrolled")
    if inp.tir_pct is not None and inp.tir_pct < t.tir_watch_floor:
        return _at_risk(f"TIR {_pct(inp.tir_pct)} · poorly controlled")

    if inp.glucose_expected and not _has_other_signal(inp):
        has_glucose_summary = (
            inp.tir_pct is not None or inp.smbg_avg is not None or inp.fasting_glucose is not None
        )
        if inp.last_glucose_days_ago is not None and inp.last_glucose_days_ago > t.no_glucose_days:
            return _data_gap(inp, t)
        if inp.glucose_reading_count_14d < t.min_readings_14d and not has_glucose_summary:
            return Triage(
                assessment=PanelAssessment.DATA_GAP,
                reason=f"Only {inp.glucose_reading_count_14d} readings / 2wk — no trend",
                severity=ReasonSeverity.WATCH,
                priority=_P_DATA_GAP,
            )

    if inp.tir_pct is not None and inp.tir_pct < t.tir_target:
        return _watch(f"TIR {_pct(inp.tir_pct)} · below target")
    if inp.a1c is not None and inp.a1c >= t.a1c_watch:
        return _watch(f"A1c {_pct(inp.a1c)} · above target")
    if inp.fasting_glucose is not None and inp.fasting_glucose > t.fasting_goal:
        return _watch(f"Fasting {_num(inp.fasting_glucose)} · above goal")
    if inp.smbg_avg is not None and inp.smbg_avg > t.smbg_goal:
        return _watch(f"SMBG avg {_num(inp.smbg_avg)} · above goal")
    if inp.tir_delta is not None and inp.tir_delta <= -t.tir_drop_mild:
        return _watch(f"TIR slipping ({inp.tir_delta:+g})")
    if inp.cv_pct is not None and inp.cv_pct > t.cv_high:
        return _watch(f"High variability · CV {_pct(inp.cv_pct)}")
    if inp.activity_dropping:
        note = inp.activity_note or "activity inconsistent"
        return _watch(f"Activity inconsistent · {note}")

    if not _assessable(inp):
        return Triage(
            assessment=PanelAssessment.DATA_GAP,
            reason="No recent data — can't assess",
            severity=ReasonSeverity.WATCH,
            priority=_P_DATA_GAP,
        )

    return Triage(
        assessment=PanelAssessment.RESPONDING,
        reason=_responding_reason(inp),
        severity=ReasonSeverity.INFO,
        priority=_P_RESPONDING,
    )


def _assessable(inp: PanelInputs) -> bool:
    return any(
        v is not None
        for v in (inp.tir_pct, inp.avg_glucose, inp.a1c, inp.fasting_glucose, inp.smbg_avg, inp.weight_delta_kg)
    )


def _has_other_signal(inp: PanelInputs) -> bool:
    return inp.a1c is not None or inp.weight_delta_kg is not None or inp.activity_dropping


def _at_risk(reason: str) -> Triage:
    return Triage(
        assessment=PanelAssessment.AT_RISK,
        reason=reason,
        severity=ReasonSeverity.URGENT,
        priority=_P_AT_RISK,
    )


def _watch(reason: str) -> Triage:
    return Triage(
        assessment=PanelAssessment.WATCH,
        reason=reason,
        severity=ReasonSeverity.WATCH,
        priority=_P_WATCH,
    )


def _data_gap(inp: PanelInputs, t) -> Triage:
    days = inp.last_glucose_days_ago
    if days is not None and days >= t.disengaged_days:
        reason = "Logging stopped ~1mo — likely disengaged"
    elif days is not None:
        reason = f"No recent glucose ({_num(days)}d) — can't assess"
    else:
        reason = "No recent glucose — can't assess"
    return Triage(
        assessment=PanelAssessment.DATA_GAP,
        reason=reason,
        severity=ReasonSeverity.WATCH,
        priority=_P_DATA_GAP,
    )


def _responding_reason(inp: PanelInputs) -> str:
    if inp.tir_pct is not None:
        return f"Stable · TIR {_pct(inp.tir_pct)}"
    if inp.weight_delta_kg is not None and inp.weight_delta_kg < 0:
        return f"On track · {_num(inp.weight_delta_kg)} kg"
    if inp.smbg_avg is not None:
        return f"On target · SMBG avg {_num(inp.smbg_avg)}"
    if inp.a1c is not None:
        return f"On target · A1c {_pct(inp.a1c)}"
    return "On track"
