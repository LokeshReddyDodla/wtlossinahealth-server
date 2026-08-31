"""Database query utilities for meal report data."""

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from lib.models.patient_meal import (
    PatientFoodItem,
    PatientMacroNutritionalValue,
    PatientMeal,
    PatientMicroNutritionalValue,
    PatientTotalMacroNutritionalValue,
    PatientTotalMicroNutritionalValue,
)


def build_meal_query(patient_id: str, start_date: date, end_date: date):
    """Build SQLAlchemy query for fetching meal data within a date range."""
    PatientFoodItemAlias = aliased(PatientFoodItem)
    PatientMacroNutritionalValueAlias = aliased(PatientMacroNutritionalValue)
    PatientMicroNutritionalValueAlias = aliased(PatientMicroNutritionalValue)

    return (
        select(
            PatientMeal.date,
            func.count(PatientMeal.id).label("meal_count"),
            *build_nutritional_aggregates(PatientMeal),
            build_meal_json(
                PatientMeal,
                PatientFoodItemAlias,
                PatientMacroNutritionalValueAlias,
                PatientMicroNutritionalValueAlias,
            ),
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
            PatientMeal.patient_id == patient_id,
            PatientMeal.date >= start_date,
            PatientMeal.date <= end_date,
        )
        .group_by(PatientMeal.date)
        .order_by(PatientMeal.date)
    )


def build_nutritional_aggregates(meal):
    """Build aggregate functions for nutritional values."""
    return [
        func.sum(PatientTotalMacroNutritionalValue.calories).label("calories"),
        func.sum(PatientTotalMacroNutritionalValue.proteins).label("proteins"),
        func.sum(PatientTotalMacroNutritionalValue.carbohydrates).label(
            "carbohydrates"
        ),
        func.sum(PatientTotalMacroNutritionalValue.simple_carbs).label(
            "simple_carbs"
        ),
        func.sum(PatientTotalMacroNutritionalValue.complex_carbs).label(
            "complex_carbs"
        ),
        func.sum(PatientTotalMacroNutritionalValue.fats).label("fats"),
        func.sum(PatientTotalMacroNutritionalValue.fiber).label("fiber"),
        func.sum(PatientTotalMicroNutritionalValue.calcium).label("calcium"),
        func.sum(PatientTotalMicroNutritionalValue.iron).label("iron"),
        func.sum(PatientTotalMicroNutritionalValue.zinc).label("zinc"),
        func.sum(PatientTotalMicroNutritionalValue.magnesium).label("magnesium"),
    ]


def build_macro_json(macro):
    """Build JSON object for macro nutritional values."""
    return func.json_build_object(
        "calories",
        macro.calories,
        "proteins",
        macro.proteins,
        "carbohydrates",
        macro.carbohydrates,
        "simple_carbs",
        macro.simple_carbs,
        "complex_carbs",
        macro.complex_carbs,
        "fats",
        macro.fats,
        "fiber",
        macro.fiber,
    )


def build_micro_json(micro):
    """Build JSON object for micro nutritional values."""
    return func.json_build_object(
        "calcium",
        micro.calcium,
        "iron",
        micro.iron,
        "zinc",
        micro.zinc,
        "magnesium",
        micro.magnesium,
    )


def build_items_json(food_item_alias, macro_alias, micro_alias, meal):
    """Build JSON aggregation for food items in a meal."""
    return (
        select(
            func.json_agg(
                func.json_build_object(
                    "id",
                    food_item_alias.id,
                    "name",
                    food_item_alias.name,
                    "center_point",
                    food_item_alias.center_point,
                    "serving_size",
                    food_item_alias.serving_size,
                    "serving_quantity",
                    food_item_alias.serving_quantity,
                    "serving_unit",
                    food_item_alias.serving_unit,
                    "macro_nutritional_values",
                    build_macro_json(macro_alias),
                    "micro_nutritional_values",
                    build_micro_json(micro_alias),
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


def build_meal_json(meal, food_item_alias, macro_alias, micro_alias):
    """Build JSON aggregation for meal data."""
    return func.json_agg(
        func.json_build_object(
            "id",
            meal.id,
            "name",
            meal.name,
            "type",
            meal.type,
            "slot",
            meal.slot,
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
            "image_url",
            meal.image_urls[1],
            "image_urls",
            meal.image_urls,
            "audio_url",
            meal.audio_url,
            "note",
            meal.note,
            "meal_analysis",
            meal.meal_analysis,
            "analyzed",
            meal.analyzed,
            "analyzed_at",
            meal.analyzed_at,
            "uploaded_at",
            meal.uploaded_at,
            "total_macro_nutritional_value",
            build_macro_json(PatientTotalMacroNutritionalValue),
            "total_micro_nutritional_value",
            build_micro_json(PatientTotalMicroNutritionalValue),
            "items",
            build_items_json(food_item_alias, macro_alias, micro_alias, meal),
        )
    ).label("meals")
