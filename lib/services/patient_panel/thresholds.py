"""Condition-aware clinical thresholds for panel triage."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Thresholds:
    tir_target: float
    tir_watch_floor: float
    fasting_goal: float
    smbg_goal: float

    very_low_pct: float
    nocturnal_hypo_pct: float
    frequent_low_events: int

    a1c_high: float
    a1c_watch: float

    tir_drop_mild: float
    cv_high: float

    no_glucose_days: float
    min_readings_14d: int
    disengaged_days: float


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
