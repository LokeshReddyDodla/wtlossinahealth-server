from datetime import date
from sqlalchemy import func, select
from lib.models.patient_meal import (
    PatientFoodItem,
    PatientMacroNutritionalValue,
    PatientMeal,
    PatientMicroNutritionalValue,
    PatientTotalMacroNutritionalValue,
    PatientTotalMicroNutritionalValue,
)
from sqlalchemy.orm import aliased


def build_meal_query(patient_id: str, start_date: date, end_date: date):
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
        func.sum(PatientTotalMacroNutritionalValue.fats).label("total_fats"),
        func.sum(PatientTotalMacroNutritionalValue.fiber).label("total_fiber"),
        func.sum(PatientTotalMicroNutritionalValue.calcium).label(
            "total_calcium"
        ),
        func.sum(PatientTotalMicroNutritionalValue.iron).label("total_iron"),
        func.sum(PatientTotalMicroNutritionalValue.zinc).label("total_zinc"),
        func.sum(PatientTotalMicroNutritionalValue.magnesium).label(
            "total_magnesium"
        ),
    ]


def build_macro_json(macro):
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


def build_micro_json(micro):
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
            build_macro_json(PatientTotalMacroNutritionalValue),
            "total_micro_nutritional_value",
            build_micro_json(PatientTotalMicroNutritionalValue),
            "items",
            build_items_json(food_item_alias, macro_alias, micro_alias, meal),
        )
    ).label("meals")
