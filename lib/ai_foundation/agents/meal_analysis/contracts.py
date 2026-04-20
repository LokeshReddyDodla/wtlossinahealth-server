"""
Meal Analysis Contracts — all Pydantic types and enums for the preview pipeline.

The agent returns MealAnalysisResult. The client sends MealPreviewRequest.
Nothing here writes to a database; save is a separate, dumb path.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from lib.schemas.patient_diet_plan import DietMealSlot


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class MealSlot(str, Enum):
    BREAKFAST = "breakfast"
    LUNCH = "lunch"
    DINNER = "dinner"
    SNACK = "snack"


class MealSource(str, Enum):
    PHOTO = "photo"
    TEXT = "text"
    REPEAT = "repeat"
    MANUAL = "manual"


class ConfidenceLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class AlternativeSource(str, Enum):
    HISTORY = "history"
    GUIDELINE = "guideline"


class PairingBenefit(str, Enum):
    GLUCOSE_BLUNT = "glucose_blunt"
    SATIETY = "satiety"
    FIBER = "fiber"
    PROTEIN = "protein"


class RepeatSuggestion(str, Enum):
    LOG_AGAIN = "log_again"
    ASK_CONFIRM = "ask_confirm"
    NONE = "none"


# ---------------------------------------------------------------------------
# Nutrition primitives
# ---------------------------------------------------------------------------


class MacroSet(BaseModel):
    calories: float = 0
    carbs: float = 0
    carbs_simple: float = 0
    carbs_complex: float = 0
    fiber: float = 0
    protein: float = 0
    fat: float = 0
    fat_saturated: float | None = None
    sugar: float | None = None


class MicroSet(BaseModel):
    sodium_mg: float | None = None
    potassium_mg: float | None = None
    calcium_mg: float | None = None
    iron_mg: float | None = None
    magnesium_mg: float | None = None
    zinc_mg: float | None = None


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


class ExtractedFoodItem(BaseModel):
    name: str
    portion: float = Field(..., description="Numeric portion amount")
    unit: str = Field(..., description="e.g. g, ml, piece, bowl, slice")
    macros: MacroSet
    micros: MicroSet | None = None
    portion_confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM
    needs_confirmation: bool = False
    tags: list[str] = Field(default_factory=list)


class MealExtraction(BaseModel):
    name: str = Field(..., description="Human-readable meal name, e.g. 'Aloo paratha with curd'")
    items: list[ExtractedFoodItem]
    total_macros: MacroSet
    total_micros: MicroSet | None = None
    tags: list[str] = Field(default_factory=list, description="e.g. high_carb, fried, plant_based")
    cuisine: str | None = None
    overall_confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


class MealScore(BaseModel):
    overall: int = Field(..., ge=0, le=100, description="0-100 composite score")
    glycemic_load: float = Field(..., description="Estimated GL: carbs_g * GI / 100")
    processed_flag: bool = False
    concerns: list[str] = Field(default_factory=list, description="Evidence-based, no moralizing")
    positives: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Alternatives + Pairings
# ---------------------------------------------------------------------------


class MealEvidenceRef(BaseModel):
    meal_id: UUID
    meal_name: str
    consumed_at: datetime
    glucose_peak: int | None = None
    glucose_peak_minutes_after: int | None = None


class Alternative(BaseModel):
    item_to_replace: str = Field(..., description="Item from current meal to swap")
    swap_with: str
    reason: str
    predicted_glucose_delta: int | None = Field(
        None, description="Estimated mg/dL reduction vs current item"
    )
    source: AlternativeSource
    frequency_in_history: int | None = None
    evidence: list[MealEvidenceRef] = Field(default_factory=list)


class Pairing(BaseModel):
    add: str = Field(..., description="Food to add to current meal")
    reason: str
    benefit: PairingBenefit


# ---------------------------------------------------------------------------
# Glucose prediction
# ---------------------------------------------------------------------------


class GlucosePrediction(BaseModel):
    range_mg_dl_low: int
    range_mg_dl_high: int
    peak_minutes_after: int
    confidence: ConfidenceLevel
    n_similar_meals: int
    evidence: list[MealEvidenceRef] = Field(default_factory=list)
    rationale: str = Field(..., description="Short natural-language explanation")


# ---------------------------------------------------------------------------
# Plan check
# ---------------------------------------------------------------------------


class PlanCheck(BaseModel):
    has_plan: bool
    slot: MealSlot
    compliant: bool | None = None
    plan_target: DietMealSlot | None = None
    deviation_summary: str | None = None


# ---------------------------------------------------------------------------
# Repeat detection
# ---------------------------------------------------------------------------


class PatientMealRef(BaseModel):
    meal_id: UUID
    meal_name: str
    consumed_at: datetime
    slot: MealSlot


class RepeatFlag(BaseModel):
    already_logged_this_slot_today: bool
    same_slot_meal_today: PatientMealRef | None = None
    same_as_previous_meal: PatientMealRef | None = None
    same_meal_count_last_7d: int = 0
    suggestion: RepeatSuggestion = RepeatSuggestion.NONE


# ---------------------------------------------------------------------------
# Request / Response
# ---------------------------------------------------------------------------


class MealPreviewRequest(BaseModel):
    """Client → server. Slot, consumed_at, source are never inferred."""

    slot: MealSlot
    source: MealSource
    consumed_at: datetime | None = Field(
        None, description="When the meal was eaten. Null = pre-emptive check ('should I eat this?')"
    )
    image_url: str | None = None
    text: str | None = None
    items: list[ExtractedFoodItem] | None = Field(
        None, description="Manual entry or edit re-preview. When set, extractor is skipped."
    )
    repeat_of_meal_id: UUID | None = Field(
        None, description="One-tap repeat. Loads prior extraction, skips extractor."
    )
    portion_note: str | None = Field(
        None, description="User hint, e.g. 'half portion', '3 slices'"
    )


class MealAnalysisResult(BaseModel):
    """Server → client. /v1/meals/preview response."""

    model_config = {"protected_namespaces": ()}

    extraction: MealExtraction
    score: MealScore
    alternatives: list[Alternative] = Field(default_factory=list)
    pairings: list[Pairing] = Field(default_factory=list)
    predicted_glucose: GlucosePrediction | None = None
    plan: PlanCheck
    repeat: RepeatFlag
    generated_at: datetime
    model_trace_id: str | None = Field(
        None, description="Langfuse trace id for this analysis"
    )


# ---------------------------------------------------------------------------
# Save path (post-confirm)
# ---------------------------------------------------------------------------


class MealCreateRequest(BaseModel):
    """Client → server. Save a confirmed (possibly edited) preview."""

    slot: MealSlot
    source: MealSource
    consumed_at: datetime
    extraction: MealExtraction
    image_url: str | None = None
    description: str | None = None
    preview_trace_id: str | None = Field(
        None, description="Links saved meal back to its preview for Langfuse quality tracking"
    )


class MealResponse(BaseModel):
    meal_id: UUID
    patient_id: UUID
    slot: MealSlot
    source: MealSource
    consumed_at: datetime
    name: str
    items: list[ExtractedFoodItem]
    total_macros: MacroSet
    total_micros: MicroSet | None = None
    tags: list[str] = Field(default_factory=list)
    image_url: str | None = None
    description: str | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
