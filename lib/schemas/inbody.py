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

EXTRACTION_SCHEMA_VERSION = "2026.07.1"

ReportStatus = Literal[
    "uploaded", "extracting", "extracted", "needs_review", "failed"
]

AbnormalityLevel = Literal["low", "normal", "high"]

# InBody's evaluation sections rate each component under / normal / over.
EvalStatus = Literal["under", "normal", "over"]

# Body-balance rows are rated balanced / slightly imbalanced / imbalanced.
BalanceStatus = Literal["balanced", "slightly_imbalanced", "imbalanced"]


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


class NutritionEvaluation(BaseModel):
    """InBody 'Nutritional Evaluation' section — each component under/normal/over."""

    protein: Optional[EvalStatus] = None
    minerals: Optional[EvalStatus] = None
    body_fat: Optional[EvalStatus] = None
    body_water: Optional[EvalStatus] = None
    summary: Optional[str] = Field(
        None, description="Overall nutritional read printed on the sheet, if any"
    )


class ObesityEvaluation(BaseModel):
    """InBody 'Obesity Evaluation' section — BMI and percent body fat rated."""

    bmi: Optional[EvalStatus] = None
    percent_body_fat: Optional[EvalStatus] = None
    summary: Optional[str] = None


class BodyBalanceEvaluation(BaseModel):
    """InBody 'Balance of Body' — upper (arms), lower (legs) and upper-lower."""

    upper: Optional[BalanceStatus] = None
    lower: Optional[BalanceStatus] = None
    upper_lower: Optional[BalanceStatus] = None
    summary: Optional[str] = None


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
    nutrition_evaluation: Optional[NutritionEvaluation] = None
    obesity_evaluation: Optional[ObesityEvaluation] = None
    body_balance_evaluation: Optional[BodyBalanceEvaluation] = None
    impedance_note: Optional[str] = Field(
        None,
        description=(
            "Short plain-language note on the segmental impedance readings "
            "(the per-segment ohm values at each frequency), e.g. whether "
            "they look consistent/typical or show an anomaly. Not the full "
            "raw grid — a one to two sentence read."
        ),
    )
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


# ---------------------------------------------------------------------------
# Contextual insight ("since your last scan")
# ---------------------------------------------------------------------------

InsightStatus = Literal["pending", "complete", "failed_retrying"]

MetricDirection = Literal["improved", "worsened", "unchanged", "unknown"]


class MetricDelta(BaseModel):
    metric: str
    previous: Optional[float] = None
    current: Optional[float] = None
    change: Optional[float] = None
    direction: MetricDirection = "unknown"


class InbodyContextualInsight(BaseModel):
    """LLM output: one scan interpreted against the behaviour window."""

    progress_story: str = Field(
        ...,
        description=(
            "Patient-facing narrative of what changed since the last scan and "
            "the likely behavioural reasons, grounded only in provided numbers. "
            "Warm, specific, under 900 characters."
        ),
    )
    what_worked: List[str] = Field(
        default_factory=list, max_length=3,
        description="Behaviours in the window that the scan results support",
    )
    likely_causes: List[str] = Field(
        default_factory=list, max_length=3,
        description="Behaviour-to-result explanations for adverse changes",
    )
    one_thing_to_improve: str = Field(
        ...,
        description="The single highest-impact change before the next scan",
    )
    care_provider_summary: str = Field(
        ...,
        description=(
            "Clinical between-visits summary: composition changes, adherence "
            "signals, risks worth discussing. Under 700 characters."
        ),
    )
    notification_title: str = Field(
        ..., description="Push title, under 60 characters"
    )
    notification_body: str = Field(
        ..., description="Push body: one-line hook into the story, under 150 characters"
    )
    data_gaps: List[str] = Field(
        default_factory=list,
        description="Domains with no data in the window — say so, never guess",
    )


class InbodyInsightRecord(BaseModel):
    insight_id: str
    report_id: str
    previous_report_id: Optional[str] = None
    patient_id: str
    status: InsightStatus
    is_baseline: bool = False
    window_start: Optional[str] = None
    window_end: Optional[str] = None
    deltas: List[MetricDelta] = Field(default_factory=list)
    insight: Optional[InbodyContextualInsight] = None
    error: Optional[str] = None
    attempts: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
