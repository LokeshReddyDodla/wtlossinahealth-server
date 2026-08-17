"""Clinical thresholds for panel triage — the single, reviewable source of the
deterministic cut-points behind PanelAssessment.

Condition-aware: pregnancy targets the tighter 63-140 range (matching the
day-view clinical alerts), everyone else the consensus 70-180. These are a
medical decision and live here so that review happens in one place — no
threshold is ever inlined in the rule engine.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Thresholds:
    tir_target: float  # TIR at/above this = on target
    tir_watch_floor: float  # tir_watch_floor ≤ TIR < tir_target = watch; below = at risk
    fasting_goal: float  # fasting above this = watch
    smbg_goal: float  # SMBG average above this = watch

    very_low_pct: float  # % time <54 mg/dL at/above this = at risk
    nocturnal_hypo_pct: float  # nocturnal % <70 at/above this = at risk
    frequent_low_events: int  # hypo events at/above this = at risk

    a1c_high: float  # A1c at/above this = at risk
    a1c_watch: float  # A1c at/above this (below a1c_high) = watch

    tir_drop_mild: float  # TIR delta ≤ -this = watch (worsening trend)
    cv_high: float  # coefficient of variation above this = watch

    no_glucose_days: float  # last glucose older than this = data gap
    min_readings_14d: int  # fewer than this in 14d (no summary metrics) = data gap
    disengaged_days: float  # last glucose older than this = "logging stopped"


STANDARD = Thresholds(
    tir_target=70,
    tir_watch_floor=50,
    fasting_goal=130,
    smbg_goal=140,
    very_low_pct=1.0,
    nocturnal_hypo_pct=5.0,
    frequent_low_events=4,
    a1c_high=9.0,
    a1c_watch=7.0,
    tir_drop_mild=5.0,
    cv_high=36.0,
    no_glucose_days=14,
    min_readings_14d=4,
    disengaged_days=25,
)

PREGNANCY = Thresholds(
    tir_target=90,
    tir_watch_floor=70,
    fasting_goal=95,
    smbg_goal=120,
    very_low_pct=1.0,
    nocturnal_hypo_pct=3.0,
    frequent_low_events=3,
    a1c_high=6.5,
    a1c_watch=6.0,
    tir_drop_mild=5.0,
    cv_high=36.0,
    no_glucose_days=7,
    min_readings_14d=8,
    disengaged_days=21,
)


def for_patient(is_pregnant: bool) -> Thresholds:
    return PREGNANCY if is_pregnant else STANDARD
