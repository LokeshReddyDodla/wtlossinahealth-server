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

from pydantic import BaseModel, Field, field_validator

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
    VOICE = "voice"
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


class EvidenceSource(str, Enum):
    """Where an insight draws its authority from.

    Every concern, positive, pairing, or alternative MUST declare one of
    these sources and supply a specific evidence string. Uncited outputs
    are dropped server-side.
    """

    PROFILE = "profile"          # patient profile fact (diet pref, allergy, condition)
    HISTORY = "history"          # cited past meal + CGM response
    PLAN = "plan"                # cited active diet plan target
    MEDICATION = "medication"    # cited active medication effect
    GUIDELINE = "guideline"      # cited published clinical rule (ADA / AHA / WHO)
    COMPOSITION = "composition"  # cited math on this meal's own macros


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
    macros: MacroSet = Field(
        default_factory=MacroSet,
        description=(
            "Nutritional macros. Client may omit when submitting a new/edited "
            "item (e.g. 'Add something we missed'); the agent re-estimates "
            "from name + portion + unit."
        ),
    )
    micros: MicroSet = Field(default_factory=MicroSet)
    portion_confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM
    needs_confirmation: bool = False
    tags: list[str] = Field(default_factory=list)

    @field_validator("macros", "micros", mode="before")
    @classmethod
    def _coerce_null_nutrition(cls, v: object) -> object:
        return v if v is not None else {}


class MealExtraction(BaseModel):
    name: str = Field(..., description="Human-readable meal name, e.g. 'Aloo paratha with curd'")
    items: list[ExtractedFoodItem]
    total_macros: MacroSet = Field(default_factory=MacroSet)
    total_micros: MicroSet = Field(default_factory=MicroSet)
    tags: list[str] = Field(default_factory=list, description="e.g. high_carb, fried, plant_based")
    cuisine: str | None = None
    overall_confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM

    @field_validator("total_macros", "total_micros", mode="before")
    @classmethod
    def _coerce_null_totals(cls, v: object) -> object:
        return v if v is not None else {}


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


class Insight(BaseModel):
    """A single cited concern or positive about the meal.

    The server drops any Insight missing ``evidence`` or with an invalid
    ``source`` before returning to the client.
    """

    text: str = Field(..., description="Short natural-language line shown to patient")
    source: EvidenceSource
    evidence: str = Field(
        ...,
        description=(
            "Specific fact being cited, e.g. 'Plan target: 60g carbs; "
            "this has 116g' or 'Past 3 parathas peaked 200+ mg/dL'."
        ),
    )


class ScoreBreakdownItem(BaseModel):
    """One weighted deduction (or bonus) that went into the score."""

    delta: int = Field(..., description="Signed score delta, e.g. -20, +10")
    source: EvidenceSource
    evidence: str


class MealScore(BaseModel):
    overall: int = Field(..., ge=0, le=100, description="Computed from cited concerns")
    glycemic_load: float = Field(..., description="Internal GL, retained for math; frontend may hide")
    concerns: list[Insight] = Field(default_factory=list)
    positives: list[Insight] = Field(default_factory=list)
    breakdown: list[ScoreBreakdownItem] = Field(
        default_factory=list,
        description="Transparent log of how 'overall' was computed from cited concerns + positives",
    )


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
    reason: str = Field(..., description="Why this swap — must reference the evidence")
    predicted_glucose_delta: int | None = Field(
        None, description="Estimated mg/dL reduction vs current item"
    )
    source: AlternativeSource
    frequency_in_history: int | None = None
    evidence: list[MealEvidenceRef] = Field(
        default_factory=list,
        description="Required for source=history: at least one past meal with CGM peak. Empty for source=guideline, in which case the reason must cite a numeric clinical rule.",
    )


class Pairing(BaseModel):
    add: str = Field(..., description="Food to add to current meal")
    reason: str
    benefit: PairingBenefit
    source: EvidenceSource = Field(
        ..., description="Pairings must cite a source; uncited pairings are dropped"
    )
    evidence: str = Field(
        ...,
        description="e.g. 'You paired oats + milk 5x last month, peaks 20 mg/dL lower' (history) or 'ADA suggests fiber with carbs to slow absorption' (guideline)",
    )


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


class MealQuickResult(BaseModel):
    """Server → client. /v1/meals/quick-preview response — extraction only."""

    model_config = {"protected_namespaces": ()}

    extraction: MealExtraction
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
    audio_url: str | None = None
    description: str | None = None
    note: str | None = Field(
        None,
        description="Free-text note from the patient ('cheat meal — wedding', 'post-workout', etc). Surfaces to the health query agent for context.",
    )
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
    audio_url: str | None = None
    description: str | None = None
    note: str | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
