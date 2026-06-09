"""Pydantic schemas for the patient workout logging API."""

from __future__ import annotations

from datetime import date as date_type, datetime, time as time_type
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

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


class PatientWorkoutCreate(BaseModel):
    date: date_type
    time: Optional[time_type] = None
    type: WorkoutType
    duration_minutes: Optional[int] = Field(None, ge=0)
    intensity: Optional[WorkoutIntensity] = None
    calories_burned: Optional[float] = Field(None, ge=0)
    notes: Optional[str] = None
    image_url: Optional[str] = None
    source: str = "app"
    fitness_plan_session_id: Optional[UUID] = None
    exercises: list[PatientWorkoutExerciseInput] = Field(default_factory=list)


class PatientWorkoutUpdate(BaseModel):
    date: Optional[date_type] = None
    time: Optional[time_type] = None
    type: Optional[WorkoutType] = None
    duration_minutes: Optional[int] = Field(None, ge=0)
    intensity: Optional[WorkoutIntensity] = None
    calories_burned: Optional[float] = Field(None, ge=0)
    notes: Optional[str] = None
    image_url: Optional[str] = None
    fitness_plan_session_id: Optional[UUID] = None
    # If provided, fully replaces the exercises list
    exercises: Optional[list[PatientWorkoutExerciseInput]] = None


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
    exercises: list[PatientWorkoutExerciseResponse]


class PatientWorkoutListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[PatientWorkoutResponse]
