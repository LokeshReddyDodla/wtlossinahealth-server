from datetime import datetime
from typing import Any

from decouple import config
from langchain.schema import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from lib.models.patient_meal import PatientFoodItem as PatientFoodItemModel
from lib.models.patient_meal import \
    PatientMacroNutritionalValue as PatientMacroNutritionalValueModel
from lib.models.patient_meal import PatientMeal as PatientMealModel
from lib.models.patient_meal import \
    PatientMicroNutritionalValue as PatientMicroNutritionalValueModel
from lib.models.patient_meal import \
    PatientTotalMacroNutritionalValue as PatientTotalMacroNutritionalValueModel
from lib.models.patient_meal import \
    PatientTotalMicroNutritionalValue as PatientTotalMicroNutritionalValueModel
from lib.schemas.patient_meal import MealAnalysisResponse
from lib.schemas.patient_meal import PatientFoodItem as PatientFoodItemSchema
from lib.schemas.patient_meal import \
    PatientMacroNutritionalValue as PatientMacroNutritionalValueSchema
from lib.schemas.patient_meal import \
    PatientMicroNutritionalValue as PatientMicroNutritionalValueSchema
from lib.utils.retry_utils import retry_request


class MealAnalysisService:
    def __init__(
        self, postgres_session: AsyncSession, timezone="Asia/Kolkata"
    ):
        self.postgres_session = postgres_session
        self.timezone = timezone

        self.chat_model = ChatOpenAI(
            model="gpt-4o",
            temperature=0.5,
            api_key=SecretStr(str(config("OPENAI_API_KEY"))),
        )
        self.structured_model = self.chat_model.with_structured_output(
            MealAnalysisResponse, include_raw=True
        )

    def analyze_meal(
        self,
        patient_profile_json,
        meal_time,
        image_url,
        meal_type,
        meal_description=None,
        update_fields=None,
    ):

        system_message = [
            SystemMessage(
                content=(
                    "You are an AI strictly focused on meal analysis with deep knowledge "
                    "of Indian cuisine and nutritional science. Respond with precise analysis "
                    "based on the given schema. Avoid unrelated topics and ensure your response "
                    "follows these considerations:\n\n"
                    "1. Identify all visible food items and provide their coordinates.\n"
                    "2. Use realistic serving sizes (grams, cups, pieces). If unclear, predict typical serving sizes "
                    "based on meal type (e.g., breakfast, lunch) and time of day.\n"
                    "3. Avoid suggesting high-GI foods with main meals unless appropriate.\n"
                    "4. Assign a score out of 10 and glycemic index tags ('high', 'medium', 'low').\n"
                    "5. Suggest culturally relevant and healthier alternatives without compromising taste.\n"
                    "6. Offer personalized feedback to align meals with macronutrient goals based on user factors.\n"
                    "7. Avoid recommending foods that may cause blood sugar spikes, "
                    "especially during breakfast, lunch, or dinner."
                )
            ),
            SystemMessage(
                content=f"Patient Profile:\n```json\n{patient_profile_json}\n```"
            ),
        ]

        human_messages = [
            HumanMessage(content=f"I had {meal_type} at {meal_time}.")
        ]

        if image_url:
            human_messages.append(
                HumanMessage(
                    content=[
                        {
                            "type": "image_url",
                            "image_url": {"url": image_url},
                        },
                    ]
                )
            )

        if meal_description:
            human_messages.append(
                HumanMessage(content=f"Description: {meal_description}")
            )

        if update_fields:
            human_messages.append(
                HumanMessage(
                    content=f"Updated Serving Details: {update_fields}"
                )
            )

        messages = system_message + human_messages

        ai_response = retry_request(
            self.structured_model.invoke,
            input=messages,
        )

        parsed_response: MealAnalysisResponse = ai_response.get("parsed", {})
        total_tokens = ai_response["raw"].usage_metadata.get("total_tokens", 0)

        return parsed_response, total_tokens

    async def reanalyze_meal(
        self,
        meal_json: dict,
        update_fields: dict,
    ):
        system_message = [
            SystemMessage(
                content=(
                    "You are an AI focused on reanalyzing meal data. "
                    "Use the provided meal details and updated serving fields "
                    "to adjust the nutritional analysis and feedback."
                )
            ),
            SystemMessage(
                content=f"Original Meal Details:\n```json\n{meal_json}\n```"
            ),
        ]

        human_messages = [
            HumanMessage(
                content="Reanalyze the meal based on the updated details."
            )
        ]

        if update_fields:
            human_messages.append(
                HumanMessage(
                    content=f"Updated Serving Details:\n```json\n{update_fields}\n```"
                )
            )

        messages = system_message + human_messages

        ai_response = retry_request(
            self.structured_model.invoke,
            input=messages,
        )

        parsed_response: MealAnalysisResponse = ai_response.get("parsed", {})
        total_tokens = ai_response["raw"].usage_metadata.get("total_tokens", 0)

        return parsed_response, total_tokens

    async def save_meal_analysis(
        self, meal: Any, analysis_data: MealAnalysisResponse
    ) -> PatientMealModel:

        # create FoodItem records
        meal.items = [
            self._create_food_item(meal, item_data)
            for item_data in analysis_data.items
        ]

        # Update total macro nutritional values
        total_macro = analysis_data.total_macro_nutritional_value.model_dump()
        meal.total_macro_nutritional_value = (
            PatientTotalMacroNutritionalValueModel(
                meal_id=meal.id, **total_macro
            )
        )

        # Update total micro nutritional values
        total_micro = analysis_data.total_micro_nutritional_value.model_dump()
        meal.total_micro_nutritional_value = (
            PatientTotalMicroNutritionalValueModel(
                meal_id=meal.id, **total_micro
            )
        )

        # Update other meal fields
        meal.name = analysis_data.meal_name
        meal.feedback = analysis_data.feedback
        meal.tags = analysis_data.tags
        meal.score = float(analysis_data.score)
        meal.analyzed = True
        meal.analyzed_at = datetime.now()

        # Commit changes to the database
        self.postgres_session.add(meal)
        await self.postgres_session.commit()

        return meal

    def _create_food_item(
        self, meal: PatientMealModel, item_data: PatientFoodItemSchema
    ) -> PatientFoodItemModel:
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

    def _upsert_total_macro_nutritional_value(
        self,
        meal: PatientMealModel,
        macro_data: PatientMacroNutritionalValueSchema,
    ) -> PatientTotalMacroNutritionalValueModel:
        return PatientTotalMacroNutritionalValueModel(meal=meal, **macro_data)

    def _upsert_total_micro_nutritional_value(
        self,
        meal: PatientMealModel,
        micro_data: PatientMicroNutritionalValueSchema,
    ) -> PatientTotalMicroNutritionalValueModel:
        return PatientTotalMicroNutritionalValueModel(meal=meal, **micro_data)
