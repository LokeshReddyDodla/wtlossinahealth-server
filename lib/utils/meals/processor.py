from datetime import datetime, timedelta, timezone
from typing import Any, List, Dict, Optional
from sqlalchemy import asc, case, func, literal_column, text
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload, aliased
from lib.models.patient_meal import (
    PatientMacroNutritionalValue,
    PatientMeal,
    PatientFoodItem,
    PatientMicroNutritionalValue,
    PatientTotalMacroNutritionalValue,
    PatientTotalMicroNutritionalValue,
)
from lib.schemas.meal_stats import (
    DailyMealStats,
)

from lib.utils.glucose.processor import GlucoseStatsProcessor
from lib.utils.glucose.summary import GlucoseSummaryStatsFetcher
from rest_server.patients.meals.api_schema import PatientMealResponse


class MealStatsProcessor:
    def __init__(self, postgres_store, clickhouse_store, patient_id: str):
        self.postgres_store = postgres_store
        self.clickhouse_store = clickhouse_store
        self.patient_id = patient_id
        self.glucose_processor = GlucoseStatsProcessor(
            clickhouse_store, postgres_store, patient_id
        )

    async def get_meal_stats_by_date(
        self, from_date: datetime, to_date: datetime
    ):
        # Fetch all glucose stats once for the entire date range
        avg_glucose_by_date = (
            GlucoseSummaryStatsFetcher.fetch_daily_average_glucose(
                self.clickhouse_store, self.patient_id, from_date, to_date
            )
        )

        # Aliases for related models
        PatientFoodItemAlias = aliased(PatientFoodItem)
        PatientMacroNutritionalValueAlias = aliased(
            PatientMacroNutritionalValue
        )
        PatientMicroNutritionalValueAlias = aliased(
            PatientMicroNutritionalValue
        )

        # Define the main query with helper functions
        query = (
            select(
                PatientMeal.date,
                func.count(PatientMeal.id).label("meal_count"),
                *self._build_nutritional_aggregates(PatientMeal),
                self._build_meal_json(
                    PatientMeal,
                    PatientFoodItemAlias,
                    PatientMacroNutritionalValueAlias,
                    PatientMicroNutritionalValueAlias,
                )
            )
            .outerjoin(
                PatientTotalMacroNutritionalValue,
                PatientMeal.total_macro_nutritional_value,
            )
            .outerjoin(
                PatientTotalMicroNutritionalValue,
                PatientMeal.total_micro_nutritional_value,
            )
            .where(
                PatientMeal.patient_id == self.patient_id,
                PatientMeal.date >= from_date,
                PatientMeal.date <= to_date,
            )
            .group_by(PatientMeal.date)
            .order_by(PatientMeal.date, asc(PatientMeal.time))
        )

        result = await self.postgres_store.execute(query)
        rows = result.all()

        return [
            self._build_daily_stats(row, avg_glucose_by_date) for row in rows
        ]

    def _build_nutritional_aggregates(self, meal):
        """Helper function to build aggregate functions for nutritional values."""
        return [
            func.sum(PatientTotalMacroNutritionalValue.calories).label(
                "total_calories"
            ),
            func.sum(PatientTotalMacroNutritionalValue.proteins).label(
                "total_proteins"
            ),
            func.sum(PatientTotalMacroNutritionalValue.carbohydrates).label(
                "total_carbohydrates"
            ),
            func.sum(PatientTotalMacroNutritionalValue.fats).label(
                "total_fats"
            ),
            func.sum(PatientTotalMacroNutritionalValue.fiber).label(
                "total_fiber"
            ),
            func.sum(PatientTotalMicroNutritionalValue.calcium).label(
                "total_calcium"
            ),
            func.sum(PatientTotalMicroNutritionalValue.iron).label(
                "total_iron"
            ),
            func.sum(PatientTotalMicroNutritionalValue.zinc).label(
                "total_zinc"
            ),
            func.sum(PatientTotalMicroNutritionalValue.magnesium).label(
                "total_magnesium"
            ),
            func.sum(PatientTotalMicroNutritionalValue.cholesterol).label(
                "total_cholesterol"
            ),
        ]

    def _build_meal_json(
        self, meal, food_item_alias, macro_alias, micro_alias
    ):
        """Helper function to build JSON aggregation for meals."""
        return func.json_agg(
            func.json_build_object(
                "id",
                meal.id,
                "name",
                meal.name,
                "type",
                meal.type,
                "date",
                meal.date,
                "time",
                meal.time,
                "description",
                meal.description,
                "source",
                meal.source,
                "tags",
                meal.tags,
                "score",
                meal.score,
                "feedback",
                meal.feedback,
                "image_url",
                meal.image_url,
                "analyzed",
                meal.analyzed,
                "analyzed_at",
                meal.analyzed_at,
                "uploaded_at",
                meal.uploaded_at,
                "total_macro_nutritional_value",
                self._build_macro_json(PatientTotalMacroNutritionalValue),
                "total_micro_nutritional_value",
                self._build_micro_json(PatientTotalMicroNutritionalValue),
                "items",
                self._build_items_json(
                    food_item_alias, macro_alias, micro_alias, meal
                ),
            )
        ).label("meals")

    def _build_macro_json(self, macro):
        """Helper function to build JSON for macro nutritional values."""
        return func.json_build_object(
            "calories",
            macro.calories,
            "proteins",
            macro.proteins,
            "carbohydrates",
            macro.carbohydrates,
            "fats",
            macro.fats,
            "fiber",
            macro.fiber,
        )

    def _build_micro_json(self, micro):
        """Helper function to build JSON for micro nutritional values."""
        return func.json_build_object(
            "calcium",
            micro.calcium,
            "iron",
            micro.iron,
            "zinc",
            micro.zinc,
            "magnesium",
            micro.magnesium,
            "cholesterol",
            micro.cholesterol,
        )

    def _build_items_json(
        self, food_item_alias, macro_alias, micro_alias, meal
    ):
        """Helper function to build JSON aggregation for meal items."""
        return (
            select(
                func.json_agg(
                    func.json_build_object(
                        "id",
                        food_item_alias.id,
                        "name",
                        food_item_alias.name,
                        "coordinates",
                        food_item_alias.coordinates,
                        "serving_size",
                        food_item_alias.serving_size,
                        "serving_quantity",
                        food_item_alias.serving_quantity,
                        "serving_unit",
                        food_item_alias.serving_unit,
                        "macro_nutritional_values",
                        self._build_macro_json(macro_alias),
                        "micro_nutritional_values",
                        self._build_micro_json(micro_alias),
                    )
                )
            )
            .select_from(food_item_alias)
            .outerjoin(macro_alias, food_item_alias.macro_nutritional_values)
            .outerjoin(micro_alias, food_item_alias.micro_nutritional_values)
            .where(food_item_alias.meal_id == meal.id)
            .correlate(meal)
            .as_scalar()
        )

    def _build_daily_stats(self, row, avg_glucose_by_date):
        """Helper function to build MealDailyStats from a query row."""

        for meal in row.meals:
            meal_time = datetime.combine(
                row.date, datetime.strptime(meal["time"], "%H:%M:%S").time()
            )
            glucose_before_meal, glucose_after_meal = (
                self.glucose_processor.fetch_glucose_around_meal(meal_time)
            )

            # Append glucose readings to each meal
            meal["glucose_before_meal"] = glucose_before_meal
            meal["glucose_after_meal"] = glucose_after_meal

        return DailyMealStats(
            date=row.date,
            meal_count=row.meal_count,
            meals=row.meals,
            calories=row.total_calories or 0,
            proteins=row.total_proteins or 0,
            carbohydrates=row.total_carbohydrates or 0,
            fats=row.total_fats or 0,
            fiber=row.total_fiber or 0,
            calcium=row.total_calcium or 0,
            iron=row.total_iron or 0,
            zinc=row.total_zinc or 0,
            magnesium=row.total_magnesium or 0,
            cholesterol=row.total_cholesterol or 0,
            avg_glucose=avg_glucose_by_date.get(row.date, 0.0),
        )
