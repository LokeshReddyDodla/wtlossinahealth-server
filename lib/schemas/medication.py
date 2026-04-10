"""Schemas for the medication/prescription system.

Three schema layers:
1. Extraction — what the LLM returns from a prescription image
2. Confirm — what the frontend sends after CP edits
3. Response — what the API returns
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


# ── Shared types ─────────────────────────────────────────────────────────────

MedicationSlot = Literal["morning", "afternoon", "evening", "night"]
DayOfWeek = Literal[0, 1, 2, 3, 4, 5, 6]  # Mon=0 .. Sun=6


class MedicationDose(BaseModel):
    slot: MedicationSlot
    quantity: float = 1


class MedicationSchedule(BaseModel):
    """Dosing frequency. NULL/absent = daily (all 7 days).

    type="weekly": alarm-style day selector, days_of_week controls which days.
    type="interval": every N days from an anchor date.
    """

    type: Literal["weekly", "interval"] = "weekly"
    days_of_week: list[DayOfWeek] = Field(
        default_factory=lambda: [0, 1, 2, 3, 4, 5, 6]
    )
    interval_days: int | None = None
    interval_anchor: date | None = None

    @model_validator(mode="after")
    def validate_schedule(self):
        if self.type == "weekly" and not self.days_of_week:
            raise ValueError("weekly schedule must have at least one day")
        if self.type == "interval":
            if not self.interval_days or self.interval_days < 1:
                raise ValueError("interval schedule requires interval_days >= 1")
            if not self.interval_anchor:
                raise ValueError("interval schedule requires interval_anchor")
        return self


# ── Extraction schemas (LLM output via gateway.extract) ─────────────────────


class ExtractedMedicine(BaseModel):
    name: str | None = None
    brand_name: str | None = None
    strength: str | None = None
    formulation: str | None = None
    route: str | None = None
    food_timing: str | None = None
    purpose: str | None = None
    instructions: str | None = None
    doses: list[MedicationDose] = Field(default_factory=list)
    schedule: MedicationSchedule | None = None
    start_date: date | None = None
    end_date: date | None = None
    is_sos: bool = False


class ExtractedPrescription(BaseModel):
    doctor_name: str | None = None
    prescription_date: date | None = None
    medicines: list[ExtractedMedicine] = Field(default_factory=list)
    follow_up_required: bool = False
    follow_up_date: date | None = None
    notes: str | None = None


# ── Confirm schemas (frontend → backend after CP edits) ─────────────────────


class ConfirmedMedicine(BaseModel):
    name: str
    brand_name: str | None = None
    strength: str | None = None
    formulation: str | None = None
    route: str | None = None
    food_timing: str | None = None
    purpose: str | None = None
    instructions: str | None = None
    doses: list[MedicationDose] = Field(default_factory=list)
    schedule: MedicationSchedule | None = None
    start_date: date
    end_date: date | None = None
    is_sos: bool = False

    @model_validator(mode="after")
    def validate_dates(self):
        if self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self


class ConfirmPrescriptionRequest(BaseModel):
    prescription_id: str | None = None  # if confirming an existing draft
    doctor_name: str | None = None
    prescription_date: date | None = None
    file_urls: list[str] = Field(default_factory=list)
    medicines: list[ConfirmedMedicine] = Field(..., min_length=1)
    follow_up_required: bool = False
    follow_up_date: date | None = None
    notes: str | None = None


# ── Response schemas (API output) ───────────────────────────────────────────


class MedicationResponse(BaseModel):
    medication_id: str
    prescription_id: str | None = None
    previous_medication_id: str | None = None
    name: str
    brand_name: str | None = None
    strength: str | None = None
    formulation: str | None = None
    route: str | None = None
    food_timing: str | None = None
    purpose: str | None = None
    instructions: str | None = None
    doses: list[MedicationDose] = Field(default_factory=list)
    schedule: MedicationSchedule | None = None
    start_date: date
    end_date: date | None = None
    is_sos: bool = False
    status: str
    days_remaining: int | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class PrescriptionResponse(BaseModel):
    prescription_id: str
    doctor_name: str | None = None
    prescription_date: date | None = None
    file_urls: list[str] = Field(default_factory=list)
    status: str
    extracted_data: dict | None = None
    uploaded_by_id: str | None = None
    uploaded_by_type: str | None = None
    follow_up_required: bool = False
    follow_up_date: date | None = None
    notes: str | None = None
    medications: list[MedicationResponse] = Field(default_factory=list)
    created_at: datetime

    class Config:
        from_attributes = True


class MedicationListResponse(BaseModel):
    active: list[MedicationResponse] = Field(default_factory=list)
    paused: list[MedicationResponse] = Field(default_factory=list)
    as_needed: list[MedicationResponse] = Field(default_factory=list)
    completed: list[MedicationResponse] = Field(default_factory=list)
