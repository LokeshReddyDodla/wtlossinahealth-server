from datetime import datetime, date
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, Field


class FitnessPlanExerciseBase(BaseModel):
    """Base model for exercise configuration in fitness plan."""
    exercise_type: str = Field(..., description="Type of exercise (e.g., cardio, strength, flexibility)")
    duration_minutes: int = Field(..., ge=1, description="Duration of exercise session in minutes")
    frequency_per_week: int = Field(..., ge=1, le=7, description="Number of times per week (1-7)")
    intensity_level: str = Field(..., description="Intensity level: low, moderate, high")


class FitnessPlanTargetBase(BaseModel):
    """Base model for fitness targets."""
    target_weight: Optional[float] = Field(None, description="Target weight in kg")
    target_bmi: Optional[float] = Field(None, description="Target BMI")
    steps_per_day: Optional[int] = Field(None, ge=0, description="Target daily steps")
    calories_burned_per_week: Optional[int] = Field(None, ge=0, description="Target calories to burn per week")


class FitnessPlanCreate(BaseModel):
    """Schema for creating a new fitness plan."""
    start_date: date = Field(..., description="Plan start date")
    end_date: date = Field(..., description="Plan end date")
    is_default: bool = Field(default=False, description="Whether this is the default fitness plan")
    status: str = Field(default="ACTIVE", description="Plan status: ACTIVE, PAUSED, COMPLETED, ARCHIVED")
    plan_reason: Optional[str] = Field(None, description="Reason for creating this plan")
    exercises: list[FitnessPlanExerciseBase] = Field(default_factory=list, description="List of exercises")
    targets: FitnessPlanTargetBase = Field(..., description="Fitness targets")
    notes: Optional[str] = Field(None, description="Additional notes")


class FitnessPlanUpdate(BaseModel):
    """Schema for updating a fitness plan."""
    start_date: Optional[date] = Field(None, description="Plan start date")
    end_date: Optional[date] = Field(None, description="Plan end date")
    is_default: Optional[bool] = Field(None, description="Whether this is the default fitness plan")
    status: Optional[str] = Field(None, description="Plan status: ACTIVE, PAUSED, COMPLETED, ARCHIVED")
    plan_reason: Optional[str] = Field(None, description="Reason for plan modification")
    exercises: Optional[list[FitnessPlanExerciseBase]] = Field(None, description="Updated exercises list")
    targets: Optional[FitnessPlanTargetBase] = Field(None, description="Updated fitness targets")
    notes: Optional[str] = Field(None, description="Updated notes")


class FitnessPlanResponse(BaseModel):
    """Schema for fitness plan responses."""
    id: UUID = Field(..., description="Plan ID")
    patient_id: UUID = Field(..., description="Patient ID")
    start_date: date = Field(..., description="Plan start date")
    end_date: date = Field(..., description="Plan end date")
    is_default: bool = Field(..., description="Whether this is the default fitness plan")
    status: str = Field(..., description="Plan status")
    plan_reason: Optional[str] = Field(None, description="Reason for plan creation")
    exercises: list[FitnessPlanExerciseBase] = Field(..., description="List of exercises")
    targets: FitnessPlanTargetBase = Field(..., description="Fitness targets")
    notes: Optional[str] = Field(None, description="Additional notes")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")

    class Config:
        from_attributes = True
