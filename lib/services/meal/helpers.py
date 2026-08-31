from datetime import date, datetime

from loguru import logger

from lib.models.patient_meal import PatientMeal as PatientMealModel
from lib.workers.tasks.meal.enqueue import (
    enqueue_meal_vector_async,
)


def _macro_dict(m: object | None) -> dict:
    if m is None:
        return {}
    return {
        "calories": m.calories,
        "proteins": m.proteins,
        "carbohydrates": m.carbohydrates,
        "simple_carbs": m.simple_carbs,
        "complex_carbs": m.complex_carbs,
        "fats": m.fats,
        "fiber": m.fiber,
    }


def _micro_dict(m: object | None) -> dict:
    if m is None:
        return {}
    return {
        "calcium": m.calcium,
        "iron": m.iron,
        "zinc": m.zinc,
        "magnesium": m.magnesium,
    }


def serialize_meal_for_vector(meal: PatientMealModel) -> dict:
    """Serialize a meal ORM row into the Qdrant vector payload shape.

    ``meal`` must be fetched with its items + total macro/micro
    relationships eager-loaded (``MealService.fetch_meal`` does this); this
    reads them directly rather than through a schema that silently drops
    unloaded relationships. Macro/micro keys match both the payload builder
    and the embedding text builder.
    """
    return {
        "meal_id": str(meal.id),
        "name": meal.name,
        "type": meal.type,
        "date": meal.date.isoformat() if meal.date else None,
        "time": meal.time.isoformat() if meal.time else None,
        "description": meal.description,
        "note": meal.note,
        "image_url": meal.image_urls[0] if meal.image_urls else None,
        "image_urls": meal.image_urls,
        "analyzed": meal.analyzed,
        "tags": meal.tags or [],
        "uploaded_at": meal.uploaded_at.isoformat() if meal.uploaded_at else None,
        "total_macro_nutritional_value": _macro_dict(meal.total_macro_nutritional_value),
        "total_micro_nutritional_value": _micro_dict(meal.total_micro_nutritional_value),
        "items": [
            {
                "name": it.name,
                "serving_quantity": it.serving_quantity,
                "serving_unit": it.serving_unit,
                "serving_size": it.serving_size,
                "macro_nutritional_values": _macro_dict(it.macro_nutritional_values),
                "micro_nutritional_values": _micro_dict(it.micro_nutritional_values),
            }
            for it in (meal.items or [])
        ],
    }


async def trigger_meal_tasks(
    patient_id: str,
    meal_id: str,
    meal_date: date,
    run_analysis: bool = True,
):
    """Trigger background tasks for meal processing.

    Only the meal id crosses to the worker; the vector task re-reads the
    meal from Postgres (source of truth) so the Qdrant point can never
    drift from what the report shows. Each enqueue fails independently and
    loudly — the vector task also drives the proactive-insight event, so a
    swallowed failure here means the meal silently never reaches Qdrant or
    the monitor.

    ``run_analysis=False`` when the client already sent its analysis (it was
    stored at save) — re-running would be a wasted LLM call and could drift
    from what the user saw.
    """
    from lib.derived import DataDomain, mark_dirty

    await mark_dirty(patient_id, DataDomain.MEAL, [meal_date])
    try:
        await enqueue_meal_vector_async(str(patient_id), str(meal_id))
    except Exception:
        logger.exception("Failed to enqueue meal vector for meal %s (%s)", meal_id, patient_id)
    if run_analysis:
        try:
            from lib.workers.tasks.meal.analysis_generation import _enqueue_meal_analysis

            await _enqueue_meal_analysis(str(patient_id), str(meal_id))
        except Exception:
            logger.exception("Failed to enqueue meal analysis for meal %s (%s)", meal_id, patient_id)
