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
from lib.utils.openai_utils import extract_json_from_response
from lib.utils.retry_utils import retry_request
import openai
from decouple import config
from lib.utils.datetime_utils import convert_milliseconds_to_datetime
from sqlalchemy.ext.asyncio import AsyncSession

from rest_server.patients.meals.api_schema import PatientMealResponse


class MealAnalysisService:
    def __init__(
        self, postgres_session: AsyncSession, api_key, timezone="Asia/Kolkata"
    ):
        self.postgres_session = postgres_session
        openai.api_key = api_key
        self.timezone = timezone

    def analyze_meal(
        self, mealtime, image_url, meal_type, food_description=None
    ):
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
        meal.name = analysis_data.get("meal_name", None)
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
        You are a dietitian expert with deep knowledge of Indian cuisine and nutritional science. Analyze the provided image considering it was taken at {mealtime}. The meal type is {meal_type}. Identify all visible food items, provide their coordinates, and give the nutritional values in the following JSON structure:
        {{
            "meal_name": "<Meal Name>",
            "meal_type": "{meal_type}",
            "items": [
                {{
                    "name": "<Dish Name>",
                    "coordinates": [left, top, right, bottom],
                    "serving_size": "serving size",
                    "serving_quantity": serving quantity,  # float
                    "serving_unit": "serving unit",
                    "macro_nutritional_values": {{
                        "calories": calories,  # float
                        "proteins": proteins,  # float
                        "carbohydrates": carbohydrates,  # float
                        "fats": fats,  # float
                        "fiber": fiber  # float
                    }},
                    "micro_nutritional_values": {{
                        "calcium": calcium,  # float
                        "iron": iron,  # float
                        "zinc": zinc,  # float
                        "magnesium": magnesium,  # float
                        "cholesterol": cholesterol  # float
                    }}
                }}
            ],
            "total_macro_nutritional_value": {{
                "calories": total calories,  # float
                "proteins": total proteins,  # float
                "carbohydrates": total carbohydrates,  # float
                "fats": total fats,  # float
                "fiber": total fiber  # float
            }},
            "total_macro_nutritional_value": {{
                "calcium": total calcium,  # float
                "iron": total iron,  # float
                "zinc": total zinc,  # float
                "magnesium": total magnesium,  # float
                "cholesterol": total cholesterol  # float
            }},
            "feedback": "personalized feedback based on the analysis and meal type, helping the user with healthier choices",
            "tags": [
                "GI tag"  # 'high', 'medium', 'low'
            ],
            "score": overall meal score  # float, out of 10
        }}
        
        Focus on identifying Indian foods and typical regional dishes where applicable. For each item:
        1. Avoid recommending foods that might cause significant blood sugar spikes, especially when analyzing meals like breakfast, lunch, or dinner. For example, avoid suggesting fruits with main meals unless they have a low glycemic index.
        2. Ensure that the feedback helps users balance their meal by aligning with average macronutrient requirements for the detected meal type. Suggest alternatives that are high in fiber without significantly raising the glycemic load, such as vegetables over high-sugar fruits.
        3. Include realistic serving sizes in familiar units (grams, cups, pieces). If exact measurements are unclear, make an informed guess.
        4. Assign glycemic index tags ('high', 'medium', 'low') based on the nutritional profile of the identified foods and provide warnings if high-GI foods are found in the context of meals where they're less appropriate.
        5. Assign a score out of 10 for the overall meal and individual items, taking into account the nutritional balance, including the impact on blood sugar levels.
        6. Provide personalized feedback that not only suggests improvements but also accounts for the timing and type of meal. For example, avoid high-sugar fruits during main meals if they might lead to a blood sugar spike.
        7. Suggest regional and culturally relevant alternatives that maintain or improve nutritional balance without compromising on taste or cultural appropriateness.
        
        Ensure your response strictly follows this structure and considerations to provide consistent and accurate nutritional analysis.
        """
