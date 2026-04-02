from datetime import date
from lib.schemas.patient_diet_plan import PatientDietPlanCreate


async def get_diet_recommendations(
    patient_id: str,
    query_date: date,
    patient_diet_plan_service,
) -> PatientDietPlanCreate:
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
        return PatientDietPlanCreate(
            calories=active_diet_plan.calories or 0,
            protein=active_diet_plan.protein or 0,
            carbs=active_diet_plan.carbs or 0,
            fats=active_diet_plan.fats or 0,
            fiber=active_diet_plan.fiber or 0,
            content=active_diet_plan.content,
            start_date=active_diet_plan.start_date,
            end_date=active_diet_plan.end_date,
        )

    # Fall back to default diet plan
    default_diet_plan = await patient_diet_plan_service.get_default_diet_plan(
        patient_id
    )

    if default_diet_plan:
        return PatientDietPlanCreate(
            calories=default_diet_plan.calories or 0,
            protein=default_diet_plan.protein or 0,
            carbs=default_diet_plan.carbs or 0,
            fats=default_diet_plan.fats or 0,
            fiber=default_diet_plan.fiber or 0,
            content=default_diet_plan.content,
            start_date=default_diet_plan.start_date,
            end_date=default_diet_plan.end_date,
        )

    # Return empty defaults if no active or default plan exists
    return PatientDietPlanCreate(
        calories=0,
        protein=0,
        carbs=0,
        fats=0,
        fiber=0,
        start_date=query_date,
    )
