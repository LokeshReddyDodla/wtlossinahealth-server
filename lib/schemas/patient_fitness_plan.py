from datetime import datetime, date as datetime_date
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# JSONB content models (validated by Pydantic, stored as JSONB in PostgreSQL)
# ---------------------------------------------------------------------------


class FitnessExercise(BaseModel):
    name: str
    sets: Optional[int] = None
    reps: Optional[int] = None
    duration_min: Optional[float] = None


class FitnessSession(BaseModel):
    day: str = Field(..., description="Day of week: monday, tuesday, etc.")
    type: str = Field(..., description="Session type: strength, cardio, flexibility, etc.")
    duration_min: Optional[float] = None
    exercises: list[FitnessExercise] = Field(default_factory=list)


class FitnessPlanContent(BaseModel):
    """Structured fitness plan content stored as JSONB.

    Example payload::

        {
          "weekly_sessions": [
            {
              "day": "monday",
              "type": "strength",
              "duration_min": 45,
              "exercises": [
                {"name": "squats", "sets": 3, "reps": 12},
                {"name": "push-ups", "sets": 3, "reps": 15},
                {"name": "dumbbell rows", "sets": 3, "reps": 12}
              ]
            },
            {
              "day": "wednesday",
              "type": "cardio",
              "duration_min": 30,
              "exercises": [
                {"name": "walking", "duration_min": 30}
              ]
            },
            {
              "day": "friday",
              "type": "strength",
              "duration_min": 45,
              "exercises": [
                {"name": "lunges", "sets": 3, "reps": 12},
                {"name": "plank", "duration_min": 1},
                {"name": "bicep curls", "sets": 3, "reps": 15}
              ]
            }
          ],
          "rest_days": ["sunday"],
          "weekly_active_minutes": 150,
          "sessions_per_week": 3,
          "notes": "Start slow, increase intensity weekly"
        }
    """
    weekly_sessions: list[FitnessSession] = Field(default_factory=list)
    rest_days: list[str] = Field(default_factory=list, description="e.g. ['sunday']")
    weekly_active_minutes: Optional[float] = None
    sessions_per_week: Optional[int] = None
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class PatientFitnessPlanCreate(BaseModel):
    """Create a fitness plan.

    Full request example::

        {
          "steps_goal": 8000,
          "start_date": "2026-04-03",
          "end_date": "2026-06-30",
          "is_default": false,
          "status": "ACTIVE",
          "plan_reason": "Increase daily activity",
          "content": {
            "weekly_sessions": [
              {
                "day": "monday",
                "type": "strength",
                "duration_min": 45,
                "exercises": [
                  {"name": "squats", "sets": 3, "reps": 12},
                  {"name": "push-ups", "sets": 3, "reps": 15}
                ]
              },
              {
                "day": "wednesday",
                "type": "cardio",
                "duration_min": 30,
                "exercises": [
                  {"name": "walking", "duration_min": 30}
                ]
              },
              {
                "day": "friday",
                "type": "strength",
                "duration_min": 45,
                "exercises": [
                  {"name": "lunges", "sets": 3, "reps": 12},
                  {"name": "plank", "duration_min": 1}
                ]
              }
            ],
            "rest_days": ["sunday"],
            "weekly_active_minutes": 150,
            "sessions_per_week": 3,
            "notes": "Start slow, increase intensity weekly"
          }
        }
    """
    steps_goal: Optional[float] = None
    content: Optional[FitnessPlanContent] = None
    start_date: datetime_date
    end_date: Optional[datetime_date] = None
    is_default: bool = False
    status: str = "ACTIVE"
    plan_reason: Optional[str] = None


class PatientFitnessPlanUpdate(BaseModel):
    steps_goal: Optional[float] = None
    content: Optional[FitnessPlanContent] = None
    start_date: Optional[datetime_date] = None
    end_date: Optional[datetime_date] = None
    is_default: Optional[bool] = None
    status: Optional[str] = None
    plan_reason: Optional[str] = None


class PatientFitnessPlan(PatientFitnessPlanCreate):
    fitness_plan_id: UUID
    patient_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
