"""Pydantic models describing intake payloads for the weightloss agent."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class AvailabilityWindow(BaseModel):
    day_of_week: str = Field(..., description="ISO weekday, e.g., mon, tue")
    start_local_time: str = Field(..., description="24h time, e.g., 06:30")
    end_local_time: str = Field(..., description="24h time, e.g., 07:15")


class IntensityPreference(BaseModel):
    floor_rpe: int = Field(3, ge=1, le=10)
    ceiling_rpe: int = Field(7, ge=1, le=10)
    notes: Optional[str] = None


class ExercisePreferencesCreate(BaseModel):
    patient_id: UUID
    preferred_modalities: List[str] = Field(default_factory=list)
    avoid_modalities: List[str] = Field(default_factory=list)
    weekly_session_target: int = Field(..., ge=1, le=28)
    session_length_minutes: int = Field(..., ge=10, le=180)
    availability: List[AvailabilityWindow] = Field(default_factory=list)
    environments: List[str] = Field(
        default_factory=list, description="e.g., indoor, outdoor, pool"
    )
    equipment_available: List[str] = Field(default_factory=list)
    intensity_preference: Optional[IntensityPreference] = None
    barriers: List[str] = Field(default_factory=list)
    motivators: List[str] = Field(default_factory=list)
    caregiver_notes: Optional[str] = None


class ExercisePreferencesRecord(ExercisePreferencesCreate):
    preference_id: UUID
    created_at: datetime
    updated_at: datetime
    version: str = "2025.03"
    provenance: dict = Field(default_factory=dict)


class MedicalFlag(BaseModel):
    code: str
    description: str
    severity: Optional[str] = None


class FitnessScreenCreate(BaseModel):
    patient_id: UUID
    resting_hr: Optional[int] = Field(None, ge=30, le=220)
    systolic_bp: Optional[int] = Field(None, ge=70, le=240)
    diastolic_bp: Optional[int] = Field(None, ge=30, le=160)
    waist_circumference_cm: Optional[float] = Field(None, ge=40, le=200)
    vo2_proxy: Optional[float] = Field(
        None, description="Submax VO2 proxy score (ml/kg/min)"
    )
    orthopedic_flags: List[MedicalFlag] = Field(default_factory=list)
    cardiometabolic_flags: List[MedicalFlag] = Field(default_factory=list)
    clearance_required: bool = False
    risk_category: Optional[str] = Field(
        None, description="low, moderate, high"
    )
    notes: Optional[str] = None


class FitnessScreenRecord(FitnessScreenCreate):
    screen_id: UUID
    screened_at: datetime
    version: str = "2025.03"
    provenance: dict = Field(default_factory=dict)


class WillingnessCommitmentCreate(BaseModel):
    patient_id: UUID
    readiness_stage: str = Field(
        ...,
        description="transtheoretical model stage identifier",
        examples=["precontemplation", "contemplation", "preparation", "action"],
    )
    commitment_score: int = Field(..., ge=1, le=5)
    weekly_minutes_promised: int = Field(..., ge=1, le=900)
    motivator_statement: Optional[str] = None
    limiting_factors: List[str] = Field(default_factory=list)
    accountability_preferences: List[str] = Field(default_factory=list)
    confidence_rating: int = Field(..., ge=0, le=10)
    support_contacts: List[str] = Field(default_factory=list)
    follow_up_interval_days: int = Field(7, ge=3, le=30)


class WillingnessCommitmentRecord(WillingnessCommitmentCreate):
    willingness_id: UUID
    captured_at: datetime
    version: str = "2025.03"
    provenance: dict = Field(default_factory=dict)
