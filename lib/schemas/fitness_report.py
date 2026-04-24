"""Pydantic schemas for the unified fitness report endpoint."""

from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel


class FitnessReportSummary(BaseModel):
    total_steps: int = 0
    avg_steps_per_day: int = 0
    total_active_energy: float = 0.0
    total_distance: float = 0.0
    total_workouts: int = 0
    total_workout_minutes: int = 0
    total_workout_calories: float = 0.0
    steps_goal: Optional[float] = None
    steps_goal_hit_days: Optional[int] = None


class DailyActivity(BaseModel):
    steps: int = 0
    active_energy: float = 0.0
    distance: float = 0.0
    flights_climbed: int = 0
    exercise_time: float = 0.0
    steps_goal_pct: Optional[float] = None


class WorkoutItem(BaseModel):
    type: str
    duration_minutes: Optional[float] = None
    calories: Optional[float] = None
    intensity: Optional[str] = None
    source: str  # "app" | "apple_health"
    workout_id: Optional[str] = None


class PlannedSession(BaseModel):
    type: str
    duration_min: Optional[float] = None


class DayPlan(BaseModel):
    steps_goal: Optional[float] = None
    planned_session: Optional[PlannedSession] = None


class FitnessDay(BaseModel):
    date: date
    activity: DailyActivity = DailyActivity()
    workouts: list[WorkoutItem] = []
    plan: Optional[DayPlan] = None


class FitnessReportResponse(BaseModel):
    patient_id: str
    start_date: date
    end_date: date
    summary: FitnessReportSummary
    days: list[FitnessDay]
