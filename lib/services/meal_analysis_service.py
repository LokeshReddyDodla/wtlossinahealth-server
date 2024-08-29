from datetime import datetime
from typing import Any
from fastapi import HTTPException
from lib.models.patient_meal import (
    PatientFoodItem,
    PatientMacroNutritionalValue,
    PatientMeal,
    PatientMicroNutritionalValue,
    PatientTotalMacroNutritionalValue,
    PatientTotalMicroNutritionalValue,
)
from lib.schemas.patient_meal import PatientMealResponse
from lib.utils.openai_utils import extract_json_from_response
from lib.utils.retry_utils import retry_request
import openai
from decouple import config
from lib.utils.datetime_utils import convert_milliseconds_to_datetime
from sqlalchemy.ext.asyncio import AsyncSession


class MealAnalysisService:
    def __init__(
        self, postgres_session: AsyncSession, api_key, timezone="Asia/Kolkata"
    ):
        self.postgres_session = postgres_session
        openai.api_key = api_key
        self.timezone = timezone

    def analyze_meal(
        self, mealtime_ms, image_url, meal_type, food_description=None
    ):
        mealtime = convert_milliseconds_to_datetime(mealtime_ms, self.timezone)
        prompt_text = self._generate_prompt(mealtime, meal_type)

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Act as a dietitian expert."},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            }
        ]

        if food_description:
            messages[0]["content"].append(
                {
                    "type": "text",
                    "text": f"Food description: {food_description}",
                }
            )

        messages[0]["content"].append({"type": "text", "text": prompt_text})

        response = retry_request(
            openai.chat.completions.create,
            max_retries=3,
            delay=2,
            model="gpt-4o",
            messages=messages,
            # max_tokens=3000,
        )

        content = (
            response.choices[0].message.content if response.choices else None
        )
        total_tokens = response.usage.total_tokens if response.usage else None

        cleaned_content = (
            extract_json_from_response(content) if content else None
        )

        return cleaned_content, total_tokens

    async def save_meal_analysis(
        self, meal: Any, analysis_data: dict
    ) -> PatientMealResponse:

        # create FoodItem records
        meal.items = [
            self._create_food_item(meal, item_data)
            for item_data in analysis_data["items"]
        ]

        # Update total macro nutritional values
        total_macro = analysis_data["total_macro_nutritional_value"]
        meal.total_macro_nutritional_value = PatientTotalMacroNutritionalValue(
            meal_id=meal.id, **total_macro
        )

        # Update total micro nutritional values
        total_micro = analysis_data["total_micro_nutritional_value"]
        meal.total_micro_nutritional_value = PatientTotalMicroNutritionalValue(
            meal_id=meal.id, **total_micro
        )

        # Update other meal fields
        meal.name = analysis_data["name"]
        meal.feedback = analysis_data["feedback"]
        meal.tags = analysis_data["tags"]
        meal.score = float(analysis_data["score"])
        meal.analyzed = True
        meal.analyzed_at = datetime.now()

        # Commit changes to the database
        self.postgres_session.add(meal)
        await self.postgres_session.commit()

        return PatientMealResponse.from_orm(meal)

    def _create_food_item(
        self, meal: PatientMeal, item_data: dict
    ) -> PatientFoodItem:
        food_item = PatientFoodItem(
            name=item_data["name"],
            coordinates=item_data["coordinates"],
            serving_size=item_data["serving_size"],
            serving_quantity=float(item_data["serving_quantity"]),
            serving_unit=item_data["serving_unit"],
            meal=meal,
        )
        food_item.macro_nutritional_values = PatientMacroNutritionalValue(
            food_item_id=food_item.id, **item_data["macro_nutritional_values"]
        )
        food_item.micro_nutritional_values = PatientMicroNutritionalValue(
            food_item_id=food_item.id, **item_data["micro_nutritional_values"]
        )
        return food_item

    def _upsert_total_macro_nutritional_value(
        self, meal: PatientMeal, macro_data: dict
    ) -> PatientTotalMacroNutritionalValue:
        return PatientTotalMacroNutritionalValue(meal=meal, **macro_data)

    def _upsert_total_micro_nutritional_value(
        self, meal: PatientMeal, micro_data: dict
    ) -> PatientTotalMicroNutritionalValue:
        return PatientTotalMicroNutritionalValue(meal=meal, **micro_data)

    def _generate_prompt(self, mealtime: datetime, meal_type: str) -> str:
        return f"""
        You are a dietitian expert. Analyze the provided image considering it was taken at {mealtime}. The meal type is {meal_type}. Identify all visible food items, provide their coordinates, and give the nutritional values in the following JSON structure:
        {{
            "meal_type": "{meal_type}",
            "items": [
                {{
                    "name": "<Dish Name>",
                    "coordinates": [<left>, <top>, <right>, <bottom>],
                    "serving_size": "<serving size>",
                    "serving_quantity": "<serving quantity>",
                    "serving_unit": "<serving unit>",
                    "macro_nutritional_values": {{
                        "calories": "<calories> kcal",
                        "proteins": "<proteins> g",
                        "carbohydrates": "<carbohydrates> g",
                        "fats": "<fats> g",
                        "fiber": "<fiber> g"
                    }},
                    "micro_nutritional_values": {{
                        "calcium": "<calcium> mg",
                        "iron": "<iron> mg",
                        "zinc": "<zinc> mg",
                        "magnesium": "<magnesium> mg",
                        "cholesterol": "<cholesterol> mg"
                    }}
                }}
            ],
            "total_macro_nutritional_value": {{
                "calories": "<total calories> kcal",
                "proteins": "<total proteins> g",
                "carbohydrates": "<total carbohydrates> g",
                "fats": "<total fats> g",
                "fiber": "<total fiber> g"
            }},
            "total_macro_nutritional_value": {{
                "calcium": "<total calcium> mg",
                "iron": "<total iron> mg",
                "zinc": "<total zinc> mg",
                "magnesium": "<total magnesium> mg",
                "cholesterol": "<total cholesterol> mg"
            }},
            "feedback": "<personalized feedback>",
            "tags": [
                "<GI tag>"
            ],
            "score": "<overall meal score>"
        }}
        
        For each item:
        1. Ensure that serving_quantity and serving_unit are consistent with serving_size. For example, if serving_size is '1/2 cup', then serving_quantity should be 0.5 and serving_unit should be 'cup'.
        2. Provide personalized feedback to help the user meet average macronutrient values for the detected meal type.
        3. Suggest similar foods from the same cuisine or region that can help improve or maintain a balanced diet.
        4. Ensure serving sizes are realistic and provided in common units such as grams, cups, or pieces. If unsure, make a best guess.
        5. Add only glycemic index tags like 'high', 'low', 'medium' based on the nutritional analysis.
        6. Assign a score (as a float) to each item and the overall meal out of 10 based on its nutritional balance.

        Please follow this structure precisely for the response and ensure the data is consistent and accurate.
        """
