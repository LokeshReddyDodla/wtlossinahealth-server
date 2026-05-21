"""Declarative manifest of required fields per onboarding section.

Single source of truth for what "complete" means. Adding a new required field
is one line here — no service code change. The service walks this manifest
on every PATCH to recompute `profile_completion` and surface what's missing.

Field paths use dotted notation from the Patient root:
    "first_name"                    → patient.first_name
    "smoking_habit.status"          → patient.smoking_habit.status
                                       (None if the relation row doesn't exist)
"""
from __future__ import annotations

from typing import Iterable


# ────────────────────────────────── Manifest ──────────────────────────────────

ONBOARDING_REQUIREMENTS: dict[str, list[str]] = {
    "basic": [
        "first_name",
        "gender",
        "dob",
        "height_cm",
        "weight_kg",
    ],
    "lifestyle": [
        "daily_activity.activity_level",
        "alcohol_consumption.status",
        "smoking_habit.status",
        "sleep_habit.sleep_quality",
        "eating_habit.meals_per_day",
    ],
    "medical_history": [
        "diabetic_history.type_of_diabetes",
    ],
}


# ─────────────────────────────────── Helpers ──────────────────────────────────

def _resolve(patient, path: str):
    """Walk a dotted path from patient. Returns None if any step is None."""
    obj = patient
    for part in path.split("."):
        if obj is None:
            return None
        obj = getattr(obj, part, None)
    return obj


def _is_set(value) -> bool:
    """Treat None and empty string as "not set". Zero / False count as set."""
    return value is not None and value != ""


def compute_section_status(patient, paths: Iterable[str]) -> tuple[bool, list[str]]:
    """Returns (is_complete, list_of_missing_paths) for a section."""
    missing = [p for p in paths if not _is_set(_resolve(patient, p))]
    return (not missing, missing)
