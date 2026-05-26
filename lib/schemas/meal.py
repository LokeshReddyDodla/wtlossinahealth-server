"""
Public meal schemas. Re-exports the canonical Pydantic types from the
meal_analysis agent contracts so services/routes depend on a stable path
and never import from deep inside ai_foundation.

Three layers:
    1. MealExtraction       — agent output (LLM-produced structure)
    2. MealAnalysisResult   — preview response (extraction + analysis)
    3. MealCreate/Response  — save + read shapes
"""

from lib.ai_foundation.agents.meal_analysis.contracts import (
    Alternative,
    AlternativeSource,
    ConfidenceLevel,
    ExtractedFoodItem,
    GlucosePrediction,
    MacroSet,
    MealAnalysisResult,
    MealCreateRequest,
    MealEvidenceRef,
    MealExtraction,
    MealPreviewRequest,
    MealQuickResult,
    MealResponse,
    MealScore,
    MealSlot,
    MealSource,
    MicroSet,
    Pairing,
    PairingBenefit,
    PatientMealRef,
    PlanCheck,
    RepeatFlag,
    RepeatSuggestion,
)

__all__ = [
    "Alternative",
    "AlternativeSource",
    "ConfidenceLevel",
    "ExtractedFoodItem",
    "GlucosePrediction",
    "MacroSet",
    "MealAnalysisResult",
    "MealCreateRequest",
    "MealEvidenceRef",
    "MealExtraction",
    "MealPreviewRequest",
    "MealQuickResult",
    "MealResponse",
    "MealScore",
    "MealSlot",
    "MealSource",
    "MicroSet",
    "Pairing",
    "PairingBenefit",
    "PatientMealRef",
    "PlanCheck",
    "RepeatFlag",
    "RepeatSuggestion",
]
