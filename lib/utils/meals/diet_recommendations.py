from datetime import date
from lib.schemas.patient_diet_plan import DietRecommendation


async def get_diet_recommendations(
    patient_id: str,
    query_date: date,
    patient_diet_plan_service,
) -> DietRecommendation:
    """Get diet recommendations for a query date.

    Returns a flat macro summary (calories, protein, carbs, fats, fiber).
    Uses the active diet plan on the query_date, or empty defaults.
    """
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

    return DietRecommendation()
