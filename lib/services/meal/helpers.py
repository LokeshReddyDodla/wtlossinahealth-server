from datetime import date, datetime
from typing import List

from loguru import logger
from markdownify import markdownify as md

from lib.core.constants import ProfileTypeEnum
from lib.models.patient_meal import PatientFoodItem as PatientFoodItemModel
from lib.models.patient_meal import (
    PatientMacroNutritionalValue as PatientMacroNutritionalValueModel,
)
from lib.models.patient_meal import (
    PatientMicroNutritionalValue as PatientMicroNutritionalValueModel,
)
from lib.models.patient_meal import PatientMeal as PatientMealModel
from lib.schemas.ai_conversation_schemas import (
    AiConversationMessage as AiConversationMessageSchema,
)
from lib.schemas.patient_meal import MealAnalysisResponse
from lib.schemas.patient_meal import PatientFoodItem as PatientFoodItemSchema
from lib.workers.tasks.meal.enqueue import (
    enqueue_daily_meal_report_async,
    enqueue_meal_vector_async,
)


def create_food_item(
    meal: PatientMealModel, item_data: PatientFoodItemSchema
) -> PatientFoodItemModel:
    """Create a food item model with nutritional values."""
    food_item = PatientFoodItemModel(
        name=item_data.name,
        coordinates=item_data.coordinates,
        serving_size=item_data.serving_size,
        serving_quantity=float(item_data.serving_quantity),
        serving_unit=item_data.serving_unit,
        category=item_data.category,
        meal=meal,
    )
    food_item.macro_nutritional_values = PatientMacroNutritionalValueModel(
        food_item_id=food_item.id,
        **item_data.macro_nutritional_values.model_dump(),
    )
    food_item.micro_nutritional_values = PatientMicroNutritionalValueModel(
        food_item_id=food_item.id,
        **item_data.micro_nutritional_values.model_dump(),
    )
    return food_item


def generate_conversation_flow(
    meal_orm, meal_id: str, parsed_ai_response: MealAnalysisResponse
) -> List[AiConversationMessageSchema]:
    """Generate conversation flow messages for meal analysis."""
    return [
        AiConversationMessageSchema(
            user_id=str(meal_orm.patient_id),
            user_type=ProfileTypeEnum.PATIENT,
            conversation_id=meal_id,
            conversation_type="meal",
            role="human",
            message_type="markdown",
            content=md(
                f"I had **{meal_orm.type}** at **{meal_orm.time.strftime('%I:%M %p')}**."
            ),
        ),
        AiConversationMessageSchema(
            user_id=str(meal_orm.patient_id),
            user_type=ProfileTypeEnum.PATIENT,
            conversation_id=meal_id,
            conversation_type="meal",
            role="human",
            message_type="image" if (meal_orm.image_urls or meal_orm.image_url) else "text",
            content=(
                str(meal_orm.image_urls[0] if meal_orm.image_urls else meal_orm.image_url)
                if (meal_orm.image_urls or meal_orm.image_url)
                else meal_orm.description or ""
            ),
        ),
        AiConversationMessageSchema(
            user_id=str(meal_orm.patient_id),
            user_type=ProfileTypeEnum.PATIENT,
            conversation_id=meal_id,
            conversation_type="meal",
            role="ai",
            message_type="text",
            content=parsed_ai_response.model_dump_json(),
            exclude_from_frontend=True,
        ),
        AiConversationMessageSchema(
            user_id=str(meal_orm.patient_id),
            user_type=ProfileTypeEnum.PATIENT,
            conversation_id=meal_id,
            conversation_type="meal",
            role="ai",
            message_type="text",
            content="How can I assist you further regarding this meal?",
        ),
    ]


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
        "image_url": meal.image_url,
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
):
    """Trigger background tasks for meal processing.

    Only the meal id crosses to the worker; the vector task re-reads the
    meal from Postgres (source of truth) so the Qdrant point can never
    drift from what the report shows. Each enqueue fails independently and
    loudly — the vector task also drives the proactive-insight event, so a
    swallowed failure here means the meal silently never reaches Qdrant or
    the monitor.
    """
    try:
        await enqueue_daily_meal_report_async(str(patient_id), meal_date)
    except Exception:
        logger.exception("Failed to enqueue daily meal report for meal %s (%s)", meal_id, patient_id)
    try:
        await enqueue_meal_vector_async(str(patient_id), str(meal_id))
    except Exception:
        logger.exception("Failed to enqueue meal vector for meal %s (%s)", meal_id, patient_id)
