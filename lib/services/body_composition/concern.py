"""Read-time clinical interpretation for body-composition metrics — the single
source of truth both clients render. Never stored: a rule change applies to every
scan on the next read, no backfill.

`position` is where a value sits vs its device-printed range; `concern` is whether
that position warrants attention.
"""

from __future__ import annotations

from typing import Any

# A HIGH reading is the concern — fat, obesity, visceral, fluid overload.
HIGH_IS_CONCERN: frozenset[str] = frozenset({
    "percent_body_fat",
    "body_fat_mass",
    "bmi",
    "obesity_degree",
    "visceral_fat_level",
    "visceral_fat_area",
    "waist_hip_ratio",
    "waist_circumference",
    "ecw_tbw_ratio",
})

# A LOW reading is the concern — muscle, cellular health, bone.
LOW_IS_CONCERN: frozenset[str] = frozenset({
    "skeletal_muscle_mass",
    "skeletal_muscle_index",
    "whole_body_phase_angle",
    "bone_mineral_content",
})

# Weight-based indices penalise muscle — a concern only when body fat is also
# above range, so a muscular person isn't flagged "obese".
MUSCLE_AWARE_ADIPOSITY: frozenset[str] = frozenset({"bmi", "obesity_degree"})


def position(value: float | None, low: float | None, high: float | None) -> str | None:
    """Where [value] sits vs its reference band. None when no range was printed."""
    if value is None or low is None or high is None:
        return None
    if value < low:
        return "below"
    if value > high:
        return "above"
    return "in_range"


def annotate(measurements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the measurements with read-time `position` and `concern` added."""
    body_fat_elevated = any(
        m.get("key") == "percent_body_fat"
        and position(m.get("value"), m.get("reference_low"), m.get("reference_high")) == "above"
        for m in measurements
    )

    annotated: list[dict[str, Any]] = []
    for m in measurements:
        key = m.get("key")
        pos = position(m.get("value"), m.get("reference_low"), m.get("reference_high"))
        verdict = "none"
        if pos == "above" and key in HIGH_IS_CONCERN:
            muscle_masked = key in MUSCLE_AWARE_ADIPOSITY and not body_fat_elevated
            verdict = "none" if muscle_masked else "alert"
        elif pos == "below" and key in LOW_IS_CONCERN:
            verdict = "alert"
        annotated.append({**m, "position": pos, "concern": verdict})
    return annotated
