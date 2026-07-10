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
    enqueue_daily_meal_report_sync,
    enqueue_meal_vector_sync,
)
from lib.schemas.patient_meal import PatientMeal as PatientMealSchema


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


def trigger_meal_tasks(
    patient_id: str,
    meal_id: str,
    meal_date: date,
    meal_obj: PatientMealModel,
):
    """Trigger background tasks for meal processing.

    Each enqueue fails independently and loudly — the vector task also
    drives the proactive-insight event, so a swallowed failure here means
    the meal silently never reaches Qdrant or the monitor.
    """
    try:
        enqueue_daily_meal_report_sync(str(patient_id), meal_date)
    except Exception:
        logger.exception("Failed to enqueue daily meal report for meal %s (%s)", meal_id, patient_id)
    try:
        enqueue_meal_vector_sync(
            str(patient_id),
            str(meal_id),
            PatientMealSchema.from_orm(meal_obj).model_dump(mode="json"),
        )
    except Exception:
        logger.exception("Failed to enqueue meal vector for meal %s (%s)", meal_id, patient_id)
