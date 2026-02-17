from datetime import date
from lib.schemas.patient_diet_plan import MealDistribution, PatientDietPlanBase


async def get_diet_recommendations(
    patient_id: str,
    query_date: date,
    patient_diet_plan_service,
) -> PatientDietPlanBase:
    """Get diet recommendations for a query date.

    Priority order:
    1. Active diet plan on the query_date
    2. Default diet plan (if no active plan exists)
    3. Empty defaults (0 values)
    """
    # Try to get active diet plan for the query date
    active_diet_plan = await patient_diet_plan_service.get_active_diet_plan(
        patient_id, query_date
    )

    if active_diet_plan:
        return PatientDietPlanBase(
            calories=active_diet_plan.calories,
            protein=active_diet_plan.protein,
            carbs=active_diet_plan.carbs,
            fats=active_diet_plan.fats,
            fiber=active_diet_plan.fiber,
            calcium=active_diet_plan.calcium,
            iron=active_diet_plan.iron,
            zinc=active_diet_plan.zinc,
            magnesium=active_diet_plan.magnesium,
            major_meal=(
                MealDistribution(**active_diet_plan.major_meal)
                if active_diet_plan.major_meal
                else None
            ),
            snack=(
                MealDistribution(**active_diet_plan.snack)
                if active_diet_plan.snack
                else None
            ),
        )

    # Fall back to default diet plan
    default_diet_plan = await patient_diet_plan_service.get_default_diet_plan(
        patient_id
    )

    if default_diet_plan:
        return PatientDietPlanBase(
            calories=default_diet_plan.calories,
            protein=default_diet_plan.protein,
            carbs=default_diet_plan.carbs,
            fats=default_diet_plan.fats,
            fiber=default_diet_plan.fiber,
            calcium=default_diet_plan.calcium,
            iron=default_diet_plan.iron,
            zinc=default_diet_plan.zinc,
            magnesium=default_diet_plan.magnesium,
            major_meal=(
                MealDistribution(**default_diet_plan.major_meal)
                if default_diet_plan.major_meal
                else None
            ),
            snack=(
                MealDistribution(**default_diet_plan.snack)
                if default_diet_plan.snack
                else None
            ),
        )

    # Return empty defaults if no active or default plan exists
    return PatientDietPlanBase(
        calories=0,
        protein=0,
        carbs=0,
        fats=0,
        fiber=0,
        calcium=0,
        iron=0,
        zinc=0,
        magnesium=0,
        major_meal=MealDistribution(
            calories=0,
            protein=0,
            carbs=0,
            fats=0,
            fiber=0,
            calcium=0,
            iron=0,
            zinc=0,
            magnesium=0,
        ),
        snack=MealDistribution(
            calories=0,
            protein=0,
            carbs=0,
            fats=0,
            fiber=0,
            calcium=0,
            iron=0,
            zinc=0,
            magnesium=0,
        ),
    )
