"""Meal Analysis Generation Task.

Runs the full detailed meal analysis (score, alternatives, pairings, plan,
predicted glucose) server-side after a meal is saved/edited, so every meal
gets it — not just the rare user who taps the "detailed insights" button.
Mirrors report/vector generation: id crosses to the worker, which re-reads
the meal from Postgres (source of truth).
"""

from datetime import datetime
from typing import Any, Dict

from loguru import logger

from lib.workers.arq.config import Queues
from lib.workers.arq.redis import enqueue_job
from lib.workers.tasks.base import TaskResult, task_with_logging


def _extraction_from_meal(meal):
    """Build a MealExtraction from a saved meal ORM row (items + macros
    eager-loaded)."""
    from lib.ai_foundation.agents.meal_analysis.contracts import (
        ConfidenceLevel,
        ExtractedFoodItem,
        MacroSet,
        MealExtraction,
    )

    def _macros(m) -> "MacroSet":
        return MacroSet(
            calories=float(getattr(m, "calories", 0) or 0),
            carbs=float(getattr(m, "carbohydrates", 0) or 0),
            carbs_simple=float(getattr(m, "simple_carbs", 0) or 0),
            carbs_complex=float(getattr(m, "complex_carbs", 0) or 0),
            fiber=float(getattr(m, "fiber", 0) or 0),
            protein=float(getattr(m, "proteins", 0) or 0),
            fat=float(getattr(m, "fats", 0) or 0),
        )

    items = [
        ExtractedFoodItem(
            name=it.name or "item",
            portion=float(it.serving_quantity or 1),
            unit=it.serving_unit or "serving",
            macros=_macros(it.macro_nutritional_values)
            if it.macro_nutritional_values
            else MacroSet(calories=0, carbs=0, carbs_simple=0, carbs_complex=0, fiber=0, protein=0, fat=0),
            portion_confidence=ConfidenceLevel.HIGH,
        )
        for it in (meal.items or [])
    ]

    totals = (
        _macros(meal.total_macro_nutritional_value)
        if meal.total_macro_nutritional_value
        else MacroSet(calories=0, carbs=0, carbs_simple=0, carbs_complex=0, fiber=0, protein=0, fat=0)
    )

    return MealExtraction(
        name=meal.name or "Meal",
        items=items,
        total_macros=totals,
        tags=list(meal.tags or []),
        overall_confidence=ConfidenceLevel.HIGH,
    )


@task_with_logging
async def generate_meal_analysis(
    ctx: Dict[str, Any],
    patient_id: str,
    meal_id: str,
) -> TaskResult:
    """Compute + store the detailed analysis for a saved meal."""
    from datetime import datetime as _dt

    from fastapi import HTTPException

    from lib.ai_foundation.agents.meal_analysis.contracts import (
        MealInsightsRequest,
        MealSlot,
        MealSource,
    )
    from lib.dependencies.service_dependencies import (
        get_meal_analysis_agent,
        get_meal_service,
    )

    meal_service = get_meal_service()
    agent = get_meal_analysis_agent()

    try:
        meal = await meal_service.fetch_meal(meal_id)
    except HTTPException:
        logger.warning(f"Meal {meal_id} gone before analysis ({patient_id})")
        return TaskResult(success=True, data={"meal_id": meal_id, "reason": "meal_gone"})

    extraction = _extraction_from_meal(meal)

    slot_value = meal.slot or meal.type
    try:
        slot = MealSlot(slot_value)
    except ValueError:
        slot = MealSlot.LUNCH
    try:
        source = MealSource(meal.source)
    except ValueError:
        source = MealSource.MANUAL

    consumed_at = _dt.combine(meal.date, meal.time) if meal.date and meal.time else None

    request = MealInsightsRequest(
        extraction=extraction,
        slot=slot,
        source=source,
        consumed_at=consumed_at,
    )

    result = await agent.insights(patient_id=patient_id, request=request)

    rows = await meal_service.store_meal_analysis(
        meal_id, result.model_dump(mode="json")
    )

    logger.info(f"Stored meal analysis for {patient_id} (meal: {meal_id}, rows={rows})")
    return TaskResult(
        success=True,
        data={
            "patient_id": patient_id,
            "meal_id": meal_id,
            "has_prediction": result.predicted_glucose is not None,
        },
    )


async def _enqueue_meal_analysis(patient_id: str, meal_id: str) -> str | None:
    """Internal: enqueue meal analysis generation."""
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    job_id = f"meal:analysis:{patient_id}:{meal_id}:{timestamp}"

    job = await enqueue_job(
        "generate_meal_analysis",
        patient_id,
        meal_id,
        _job_id=job_id,
        _queue_name=Queues.DEFAULT,
    )

    if job:
        logger.info(f"Enqueued meal analysis for {patient_id} (meal: {meal_id})")
    else:
        logger.debug(f"Duplicate meal analysis skipped: {job_id}")

    return job.job_id if job else None
