from datetime import date
from lib.schemas.patient_diet_plan import DietRecommendation


async def get_diet_recommendations(
    patient_id: str,
    query_date: date,
    patient_diet_plan_service,
) -> DietRecommendation:
    """Get diet recommendations for a query date.

    Returns a flat macro summary (calories, protein, carbs, fats, fiber).

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
        return DietRecommendation(
            calories=active_diet_plan.calories or 0,
            protein=active_diet_plan.protein or 0,
            carbs=active_diet_plan.carbs or 0,
            fats=active_diet_plan.fats or 0,
            fiber=active_diet_plan.fiber or 0,
        )

    # Fall back to default diet plan
    default_diet_plan = await patient_diet_plan_service.get_default_diet_plan(
        patient_id
    )

    if default_diet_plan:
        return DietRecommendation(
            calories=default_diet_plan.calories or 0,
            protein=default_diet_plan.protein or 0,
            carbs=default_diet_plan.carbs or 0,
            fats=default_diet_plan.fats or 0,
            fiber=default_diet_plan.fiber or 0,
        )

    # Return empty defaults if no active or default plan exists
    return DietRecommendation()
