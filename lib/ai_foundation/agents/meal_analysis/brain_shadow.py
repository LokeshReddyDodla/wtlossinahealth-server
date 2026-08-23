"""Shadow runner for ``aihealth_brain.assess`` on the meal preview path.

When the flag is off this module is a no-op. When on, it calls assess,
writes one ``brain_shadow`` log row, and never returns a value the
caller may assign onto ``GlucosePrediction``.
"""

from __future__ import annotations

import logging
from typing import Any

from lib.ai_foundation.agents.meal_analysis.context_loader import (
    MealAnalysisContext,
)
from lib.ai_foundation.agents.meal_analysis.contracts import MealExtraction
from lib.ai_foundation.clinical.aihealth_brain import (
    alias_cgm_events,
    sanitize_assess_result,
)

logger = logging.getLogger(__name__)


def meal_dict_from_extraction(
    extraction: MealExtraction,
    *,
    live_pre: float | None,
    hour: int | None,
) -> dict[str, Any]:
    """Map extraction macros to the engine meal dict (field names only)."""
    macros = extraction.total_macros
    return {
        "carb": macros.carbs,
        "protein": macros.protein,
        "fat": macros.fat,
        "fiber": macros.fiber,
        "cal": macros.calories,
        "pre": live_pre,
        "hour": hour,
    }


def patient_state_from_context(context: MealAnalysisContext) -> dict[str, Any]:
    """Build an assess() state from already-loaded preview context.

    History is a field remap of recent meals. Missing peak/pre stay
    absent — this path does not invent CGM pairing numbers.
    """
    history: list[dict[str, Any]] = []
    for meal in context.recent_meals or []:
        macros = meal.get("macros") or meal.get("nutrition") or {}
        carb = (
            macros.get("carbohydrates")
            or macros.get("carbs")
            or macros.get("carb")
        )
        if carb is None:
            continue
        hour = None
        consumed = meal.get("consumed_at") or meal.get("time") or ""
        if isinstance(consumed, str) and "T" in consumed:
            try:
                hour = int(consumed.split("T", 1)[1][:2])
            except (TypeError, ValueError):
                hour = None
        history.append(
            {
                "carb": carb,
                "protein": macros.get("proteins") or macros.get("protein"),
                "fiber": macros.get("fiber"),
                "cal": macros.get("calories") or macros.get("cal"),
                "pre": meal.get("pre_meal_glucose") or meal.get("pre"),
                "hour": hour,
                "peak": meal.get("glucose_rise") or meal.get("peak"),
            }
        )
    return alias_cgm_events(
        {
            "history": history,
            "events": list(context.cgm_events or []),
            "profile": context.profile or {},
        }
    )


def maybe_shadow_brain(
    *,
    enabled: bool,
    patient_id: str,
    extraction: MealExtraction,
    context: MealAnalysisContext,
    live_pre: float | None,
    meal_hour: int | None,
    trace_id: str | None = None,
) -> dict[str, Any] | None:
    """Run assess() for a log row only. Exceptions never escape."""
    if not enabled:
        return None
    try:
        try:
            from aihealth_brain import assess
        except ImportError:
            from lib.ai_foundation.clinical.aihealth_brain import assess

        state = patient_state_from_context(context)
        meal = meal_dict_from_extraction(
            extraction, live_pre=live_pre, hour=meal_hour
        )
        raw = assess(state, meal)
        result = sanitize_assess_result(raw)
        if not isinstance(result, dict):
            logger.warning(
                "brain_shadow patient=%s non-dict result; skipped",
                patient_id,
            )
            return None
        lever = result.get("lever") or {}
        pred = result.get("prediction") or {}
        logger.info(
            "brain_shadow patient=%s output_mode=%s safety_flags=%s "
            "lever=%s rise=%s trace_id=%s",
            patient_id,
            result.get("output_mode"),
            result.get("safety_flags"),
            lever.get("name") if isinstance(lever, dict) else None,
            pred.get("rise_mgdl") if isinstance(pred, dict) else None,
            trace_id,
        )
        return result
    except Exception:
        logger.exception(
            "brain_shadow failed for %s; serving path unchanged", patient_id
        )
        return None
