"""
Plan checker.

Deterministic comparison between a meal extraction and the patient's
active diet plan for the relevant slot. No LLM. No moralizing — just
factual deviation reporting.
"""

from __future__ import annotations

import logging
from typing import Any

from lib.schemas.patient_diet_plan import DietMealSlot, DietPlanContent

from .contracts import MealExtraction, MealSlot, PlanCheck

logger = logging.getLogger(__name__)


# Tolerance bands for calling something "compliant". Calories allow +/-15%;
# macros looser at +/-25% because estimates are noisy at the per-meal level.
CAL_TOLERANCE = 0.15
MACRO_TOLERANCE = 0.25


def check_plan(
    *,
    extraction: MealExtraction,
    slot: MealSlot,
    active_plan: Any | None,
) -> PlanCheck:
    """Compare extraction to active_plan's slot target. Returns PlanCheck."""
    if active_plan is None:
        return PlanCheck(has_plan=False, slot=slot)

    slot_target = _extract_slot_target(active_plan, slot)
    if slot_target is None:
        return PlanCheck(
            has_plan=True,
            slot=slot,
            compliant=None,
            deviation_summary="No target set for this slot in the active plan.",
        )

    deltas = _compute_deltas(extraction, slot_target)
    compliant = _is_compliant(deltas)
    deviation = _summarize_deviation(deltas) if not compliant else None

    return PlanCheck(
        has_plan=True,
        slot=slot,
        compliant=compliant,
        plan_target=slot_target,
        deviation_summary=deviation,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_slot_target(plan: Any, slot: MealSlot) -> DietMealSlot | None:
    """Pull the DietMealSlot for the given slot from plan.content.meals.

    Accepts either a payload dict or an ORM model with a `content` field.
    """
    if plan is None:
        return None

    if isinstance(plan, dict):
        content = plan.get("content")
    else:
        content = getattr(plan, "content", None)
    if content is None:
        return None

    if isinstance(content, dict):
        try:
            content = DietPlanContent.model_validate(content)
        except Exception as exc:
            logger.debug("plan.content failed to validate: %s", exc)
            return None

    for meal in getattr(content, "meals", []) or []:
        meal_slot = (meal.slot or "").strip().lower()
        if meal_slot == slot.value:
            return meal
    return None


def _compute_deltas(
    extraction: MealExtraction, target: DietMealSlot
) -> dict[str, dict[str, float]]:
    """Return per-nutrient actual vs target vs delta_pct."""
    m = extraction.total_macros
    actual = {
        "calories": m.calories or 0,
        "carbs": m.carbs or 0,
        "protein": m.protein or 0,
        "fats": m.fat or 0,
    }
    target_values = {
        "calories": target.calories or 0,
        "carbs": target.carbs or 0,
        "protein": target.protein or 0,
        "fats": target.fats or 0,
    }

    out: dict[str, dict[str, float]] = {}
    for k, a in actual.items():
        t = target_values[k]
        delta = a - t
        delta_pct = (delta / t) if t > 0 else 0.0
        out[k] = {"actual": a, "target": t, "delta": delta, "delta_pct": delta_pct}
    return out


def _is_compliant(deltas: dict[str, dict[str, float]]) -> bool:
    cal = deltas["calories"]["delta_pct"]
    if abs(cal) > CAL_TOLERANCE:
        return False
    for k in ("carbs", "protein", "fats"):
        if abs(deltas[k]["delta_pct"]) > MACRO_TOLERANCE:
            return False
    return True


def _summarize_deviation(deltas: dict[str, dict[str, float]]) -> str:
    parts: list[str] = []
    for key, label in (
        ("calories", "calories"),
        ("carbs", "carbs"),
        ("protein", "protein"),
        ("fats", "fats"),
    ):
        d = deltas[key]
        tol = CAL_TOLERANCE if key == "calories" else MACRO_TOLERANCE
        if d["target"] <= 0 or abs(d["delta_pct"]) <= tol:
            continue
        direction = "over" if d["delta"] > 0 else "under"
        parts.append(
            f"{label} {direction} by {abs(d['delta']):.0f} "
            f"({abs(d['delta_pct']) * 100:.0f}%)"
        )
    if not parts:
        return "Within tolerance overall but outside per-nutrient band."
    return "; ".join(parts)
