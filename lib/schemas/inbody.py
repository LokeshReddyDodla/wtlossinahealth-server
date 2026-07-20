"""Typed schemas for the standalone InBody report domain.

``InbodyExtraction`` is the versioned LLM vision-extraction target — the
contract between the extractor and everything downstream. When the official
InBody API replaces uploads, its adapter writes this same shape.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

EXTRACTION_SCHEMA_VERSION = "2026.07"

ReportStatus = Literal[
    "uploaded", "extracting", "extracted", "needs_review", "failed"
]

AbnormalityLevel = Literal["low", "normal", "high"]


# ---------------------------------------------------------------------------
# Extraction target (LLM output)
# ---------------------------------------------------------------------------


class InbodyMeasurement(BaseModel):
    name: str = Field(
        ...,
        description=(
            "Canonical snake_case measurement name, e.g. 'weight', "
            "'skeletal_muscle_mass', 'body_fat_mass', 'percent_body_fat', "
            "'bmi', 'basal_metabolic_rate', 'visceral_fat_level', "
            "'total_body_water', 'ecw_ratio', 'waist_hip_ratio', 'phase_angle'"
        ),
    )
    value: float
    unit: Optional[str] = Field(None, description="e.g. kg, %, kcal, L")
    normal_range_low: Optional[float] = None
    normal_range_high: Optional[float] = None
    level: Optional[AbnormalityLevel] = Field(
        None, description="Where the value sits relative to its normal range"
    )


class SegmentalValue(BaseModel):
    segment: Literal[
        "right_arm", "left_arm", "trunk", "right_leg", "left_leg"
    ]
    mass_kg: Optional[float] = None
    percent_of_normal: Optional[float] = Field(
        None, description="Value relative to 100% = ideal for this segment"
    )
    level: Optional[AbnormalityLevel] = None


class WeightControl(BaseModel):
    target_weight_kg: Optional[float] = None
    weight_control_kg: Optional[float] = Field(
        None, description="Recommended weight change; negative = lose"
    )
    fat_control_kg: Optional[float] = None
    muscle_control_kg: Optional[float] = None


class InbodyExtraction(BaseModel):
    """Everything readable from one InBody result sheet."""

    schema_version: str = EXTRACTION_SCHEMA_VERSION
    report_date: Optional[str] = Field(
        None, description="Test date printed on the sheet, ISO YYYY-MM-DD"
    )
    inbody_score: Optional[int] = Field(None, ge=0, le=100)
    measurements: List[InbodyMeasurement] = Field(default_factory=list)
    segmental_lean: List[SegmentalValue] = Field(default_factory=list)
    segmental_fat: List[SegmentalValue] = Field(default_factory=list)
    weight_control: Optional[WeightControl] = None
    device_model: Optional[str] = Field(
        None, description="e.g. 'InBody 770' if printed on the sheet"
    )
    extraction_confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description=(
            "Self-assessed confidence that all legible values were captured "
            "correctly; below 0.7 routes the report to needs_review"
        ),
    )
    notes: Optional[str] = Field(
        None, description="Anything illegible, cropped or ambiguous"
    )


# ---------------------------------------------------------------------------
# API responses
# ---------------------------------------------------------------------------


class InbodyReportRecord(BaseModel):
    report_id: UUID
    patient_id: UUID
    file_url: str
    original_filename: Optional[str] = None
    report_date: date
    status: ReportStatus
    uploaded_by_role: Optional[str] = None
    error: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class InbodyReportDetail(InbodyReportRecord):
    analysis: Optional[InbodyExtraction] = None


class TrendPoint(BaseModel):
    report_id: UUID
    report_date: date
    value: float


class InbodyTrend(BaseModel):
    metric: str
    unit: Optional[str] = None
    points: List[TrendPoint] = Field(default_factory=list)
    change: Optional[float] = Field(
        None, description="last value minus first value over the window"
    )


class InbodyTrendsResponse(BaseModel):
    patient_id: UUID
    reports_count: int
    first_report_date: Optional[date] = None
    last_report_date: Optional[date] = None
    trends: List[InbodyTrend] = Field(default_factory=list)
