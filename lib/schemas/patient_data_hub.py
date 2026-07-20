"""Typed shapes for the Patient Data Hub — the read-only aggregation layer.

Features read patient data through the hub instead of querying the six
stores directly; anything the hub returns is derived from the domain
sources of truth and never written back.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class WindowAggregates(BaseModel):
    """Cross-domain aggregates over a patient-local date window."""

    patient_id: str
    start_date: str
    end_date: str
    days_in_window: int

    # Meals
    days_with_meals: int = 0
    avg_daily_calories: Optional[float] = None
    avg_daily_protein_g: Optional[float] = None
    avg_daily_carbs_g: Optional[float] = None
    avg_daily_fats_g: Optional[float] = None
    avg_daily_fiber_g: Optional[float] = None

    # Fitness
    days_with_steps: int = 0
    avg_daily_steps: Optional[int] = None
    workouts_count: int = 0
    workout_minutes_total: int = 0
    workout_exercises: List[str] = Field(
        default_factory=list,
        description="Distinct exercise names logged in the window",
    )

    # Sleep
    days_with_sleep: int = 0
    avg_sleep_hours: Optional[float] = None

    # Glucose
    days_with_glucose: int = 0
    avg_glucose_mgdl: Optional[float] = None
    avg_time_in_range_percent: Optional[float] = None

    # Weight
    first_weight_kg: Optional[float] = None
    last_weight_kg: Optional[float] = None

    # Medications (state, not adherence)
    active_medications: List[str] = Field(default_factory=list)
    glp1_active: bool = False

    data_coverage: List[str] = Field(
        default_factory=list,
        description="Domains that actually had data in the window",
    )
