"""GLP-1 weekly symptoms schema definitions."""

from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class SymptomEntry(BaseModel):
    name: str
    severity_grade: int = Field(..., ge=0, le=3)
    days_reported: int = Field(..., ge=0, le=7)
    notes: Optional[str] = None


class WeeklySymptomsCreate(BaseModel):
    user_id: UUID
    medication_name: Optional[str] = None
    medication_dose_mg: Optional[float] = None
    week_start: date
    week_end: date
    symptoms: List[SymptomEntry] = Field(default_factory=list)
    fasting_bg_events: int = Field(0, ge=0)
    hypoglycemia_events: int = Field(0, ge=0)
    insulin_or_sulfonylurea: bool = False
    notes: Optional[str] = None


class WeeklySymptomsRecord(WeeklySymptomsCreate):
    record_id: UUID
    captured_at: datetime
    severity_grade_overall: int = Field(0, ge=0, le=3)
    escalation_triggered: bool = False
    escalation_reason: Optional[str] = None
    provenance: dict = Field(default_factory=dict)
