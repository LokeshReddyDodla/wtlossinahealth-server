"""Schemas for the doctor-patient consultation recording feature.

Three layers:
1. Extraction — what the LLM returns from a transcript
2. Document   — Mongo storage shape
3. Response   — what the API returns
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from lib.schemas.medication import ExtractedMedicine


ConsultationStatus = Literal["draft"]


# ── Extraction (LLM output via ModelGateway.extract) ────────────────────────


class ExtractedConsultation(BaseModel):
    """Structured insights extracted from a doctor-patient conversation.

    Fields are intentionally aligned with PatientPrescription + PatientMedication
    so a consultation can later be promoted into those rows with no remapping.
    """

    # Provider & visit metadata
    doctor_name: str | None = None
    prescription_date: date | None = None

    # Clinical narrative
    chief_complaint: str | None = None
    history_of_present_illness: str | None = None
    past_history_mentioned: str | None = None
    examination_findings: str | None = None
    assessment: str | None = None
    plan: str | None = None

    # Prescription-flavored outputs
    medicines: list[ExtractedMedicine] = Field(default_factory=list)
    investigations_ordered: list[str] = Field(default_factory=list)
    lifestyle_advice: list[str] = Field(default_factory=list)

    # Follow-up (structured for direct PatientPrescription mapping)
    follow_up_required: bool = False
    follow_up_date: date | None = None
    follow_up_instructions: str | None = None

    # Misc
    notes: str | None = None
    red_flags: list[str] = Field(default_factory=list)
    summary: str | None = None


# ── Response (API → frontend) ────────────────────────────────────────────────


class ConsultationResponse(BaseModel):
    """Full consultation record returned by the API."""

    consultation_id: str
    patient_id: str
    audio_url: str
    audio_duration_seconds: float | None = None
    transcript: str | None = None
    extracted_data: ExtractedConsultation | None = None
    status: ConsultationStatus
    recorded_by_id: str
    recorded_by_type: str
    recorded_at: datetime
    created_at: datetime
    updated_at: datetime


class ConsultationListItem(BaseModel):
    """Compact list-view representation (no full transcript)."""

    consultation_id: str
    patient_id: str
    audio_duration_seconds: float | None = None
    status: ConsultationStatus
    chief_complaint: str | None = None
    summary: str | None = None
    recorded_by_id: str
    recorded_by_type: str
    recorded_at: datetime
    created_at: datetime
