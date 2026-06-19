"""Pydantic schemas for the patient workout logging API."""

from __future__ import annotations

from datetime import date as date_type, datetime, time as time_type
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

WorkoutType = Literal["strength", "cardio", "hiit", "mobility", "mixed", "other"]
WorkoutIntensity = Literal["light", "moderate", "vigorous"]


class WorkoutSetInput(BaseModel):
    set_number: int = Field(ge=1)
    reps: Optional[int] = Field(None, ge=1)
    weight_kg: Optional[float] = Field(None, ge=0)
    duration_seconds: Optional[int] = Field(None, ge=0)
    distance_m: Optional[float] = Field(None, ge=0)


class PatientWorkoutExerciseInput(BaseModel):
    exercise_id: str
    order_index: int = 0
    sets: Optional[int] = Field(None, ge=1)
    reps: Optional[int] = Field(None, ge=1)
    weight_kg: Optional[float] = Field(None, ge=0)
    duration_seconds: Optional[int] = Field(None, ge=0)
    distance_m: Optional[float] = Field(None, ge=0)
    notes: Optional[str] = None
    set_details: Optional[list[WorkoutSetInput]] = None


# ── Segment schemas ─────────────────────────────────────────────────────


class PatientWorkoutSegmentInput(BaseModel):
    type: WorkoutType
    duration_minutes: Optional[int] = Field(None, ge=0)
    order_index: int = 0
    exercises: list[PatientWorkoutExerciseInput] = Field(default_factory=list)


class PatientWorkoutSegmentResponse(BaseModel):
    id: UUID
    type: str
    duration_minutes: Optional[int] = None
    order_index: int
    exercises: list[PatientWorkoutExerciseResponse] = Field(default_factory=list)


# ── Create / Update ─────────────────────────────────────────────────────


class PatientWorkoutCreate(BaseModel):
    date: date_type
    time: Optional[time_type] = None
    # Legacy fields — used when segments is empty (backward compat for old clients)
    type: Optional[WorkoutType] = None
    duration_minutes: Optional[int] = Field(None, ge=0)
    exercises: list[PatientWorkoutExerciseInput] = Field(default_factory=list)

    intensity: Optional[WorkoutIntensity] = None
    calories_burned: Optional[float] = Field(None, ge=0)
    notes: Optional[str] = None
    image_url: Optional[str] = None
    source: str = "app"
    fitness_plan_session_id: Optional[UUID] = None

    segments: list[PatientWorkoutSegmentInput] = Field(default_factory=list)

    @model_validator(mode="after")
    def _normalize_segments(self) -> PatientWorkoutCreate:
        if self.segments:
            return self
        if self.type is not None:
            self.segments = [
                PatientWorkoutSegmentInput(
                    type=self.type,
                    duration_minutes=self.duration_minutes,
                    order_index=0,
                    exercises=self.exercises,
                )
            ]
            return self
        raise ValueError("Either 'segments' or 'type' must be provided")


class PatientWorkoutUpdate(BaseModel):
    date: Optional[date_type] = None
    time: Optional[time_type] = None
    # Legacy fields — used when segments is absent (backward compat for old clients)
    type: Optional[WorkoutType] = None
    duration_minutes: Optional[int] = Field(None, ge=0)
    exercises: Optional[list[PatientWorkoutExerciseInput]] = None

    intensity: Optional[WorkoutIntensity] = None
    calories_burned: Optional[float] = Field(None, ge=0)
    notes: Optional[str] = None
    image_url: Optional[str] = None
    fitness_plan_session_id: Optional[UUID] = None

    segments: Optional[list[PatientWorkoutSegmentInput]] = None

    @model_validator(mode="after")
    def _normalize_segments(self) -> PatientWorkoutUpdate:
        if self.segments is not None:
            return self
        if self.exercises is not None:
            seg_type = self.type or "other"
            self.segments = [
                PatientWorkoutSegmentInput(
                    type=seg_type,
                    duration_minutes=self.duration_minutes,
                    order_index=0,
                    exercises=self.exercises,
                )
            ]
        return self


# ── Response schemas ────────────────────────────────────────────────────


class WorkoutSetResponse(BaseModel):
    id: UUID
    set_number: int
    reps: Optional[int] = None
    weight_kg: Optional[float] = None
    duration_seconds: Optional[int] = None
    distance_m: Optional[float] = None


class PatientWorkoutExerciseResponse(BaseModel):
    id: UUID
    exercise_id: str
    exercise_name: str
    order_index: int
    sets: Optional[int] = None
    reps: Optional[int] = None
    weight_kg: Optional[float] = None
    duration_seconds: Optional[int] = None
    distance_m: Optional[float] = None
    notes: Optional[str] = None
    set_details: list[WorkoutSetResponse] = Field(default_factory=list)


class PatientWorkoutResponse(BaseModel):
    id: UUID
    patient_id: UUID
    date: date_type
    time: Optional[time_type] = None
    type: str
    duration_minutes: Optional[int] = None
    intensity: Optional[str] = None
    calories_burned: Optional[float] = None
    notes: Optional[str] = None
    image_url: Optional[str] = None
    source: str
    fitness_plan_session_id: Optional[UUID] = None
    uploaded_at: datetime
    segments: list[PatientWorkoutSegmentResponse] = Field(default_factory=list)
    exercises: list[PatientWorkoutExerciseResponse] = Field(default_factory=list)


class PatientWorkoutListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[PatientWorkoutResponse]
