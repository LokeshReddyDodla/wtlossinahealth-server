from datetime import date
from lib.schemas.patient_diet_plan import MealDistribution, PatientDietPlanBase
from lib.utils.diet_plan_calculator import DietPlanCalculator


async def get_diet_recommendations(
    patient_id: str,
    query_date: date,
    patient_plan_service,
    patient_profile_service,
) -> PatientDietPlanBase:
    """Fetch diet recommendations from an active plan or calculate dynamically."""
    active_plan = await patient_plan_service.get_active_patient_plan(
        patient_id, query_date
    )

    if active_plan and active_plan.diet_plan:
        return PatientDietPlanBase(
            total_calories=active_plan.diet_plan.total_calories,
            protein=active_plan.diet_plan.protein,
            carbs=active_plan.diet_plan.carbs,
            fats=active_plan.diet_plan.fats,
            fiber=active_plan.diet_plan.fiber,
            calcium=active_plan.calcium,
            iron=active_plan.iron,
            zinc=active_plan.zinc,
            magnesium=active_plan.magnesium,
            major_meal=(
                MealDistribution(**active_plan.diet_plan.major_meal)
                if active_plan.diet_plan.major_meal
                else None
            ),
            snack=(
                MealDistribution(**active_plan.diet_plan.snack)
                if active_plan.diet_plan.snack
                else None
            ),
        )
    else:
        return await calculate_recommendations(
            patient_id, patient_profile_service
        )


async def calculate_recommendations(patient_id: str, patient_profile_service):
    """Calculate recommendations dynamically if no active plan exists."""
    patient = await patient_profile_service.fetch_patient_profile(
        patient_id, detailed=True
    )

    if (
        patient.weight is None
        or patient.height is None
        or patient.dob is None
        or patient.gender is None
    ):
        # Return default values if the profile is incomplete
        return PatientDietPlanBase(
            total_calories=0,
            protein=0,
            carbs=0,
            fats=0,
            fiber=0,
            calcium=0,
            iron=0,
            zinc=0,
            magnesium=0,
            major_meal=MealDistribution(
                total_calories=0,
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
                total_calories=0,
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

    # age = calculate_age(patient.dob)
    age = 24
    calculator = DietPlanCalculator(
        weight=patient.weight,
        height=patient.height,
        age=age,
        gender=patient.gender,
        activity_level=(
            patient.daily_activity.activity_level
            if patient.daily_activity
            else "sedentary"
        ),
    )

    tdee = calculator.calculate_tdee()
    macronutrients = calculator.calculate_macronutrients(tdee)
    micronutrients = calculator.get_micronutrient_recommendations()

    meals_per_day = getattr(patient.eating_habit, "meals_per_day", 3) or 3
    snacks_count = getattr(patient.eating_habit, "snacks_count", 2) or 2

    # Calculate the ratio for major meals and snacks based on their count
    total_meal_count = meals_per_day + snacks_count
    major_meal_ratio = meals_per_day / total_meal_count
    snack_ratio = snacks_count / total_meal_count

    # Calculate per-meal recommendations for major meals
    major_meal_distribution = MealDistribution(
        total_calories=(tdee * major_meal_ratio) / meals_per_day,
        protein=(macronutrients["protein"] * major_meal_ratio) / meals_per_day,
        carbs=(macronutrients["carbs"] * major_meal_ratio) / meals_per_day,
        fats=(macronutrients["fats"] * major_meal_ratio) / meals_per_day,
        fiber=(micronutrients["fiber"] * major_meal_ratio) / meals_per_day,
        calcium=(micronutrients["calcium"] * major_meal_ratio) / meals_per_day,
        iron=(micronutrients["iron"] * major_meal_ratio) / meals_per_day,
        zinc=(micronutrients["zinc"] * major_meal_ratio) / meals_per_day,
        magnesium=(micronutrients["magnesium"] * major_meal_ratio)
        / meals_per_day,
    )

    # Calculate per-snack recommendations for snacks
    snack_distribution = MealDistribution(
        total_calories=(tdee * snack_ratio) / snacks_count,
        protein=(macronutrients["protein"] * snack_ratio) / snacks_count,
        carbs=(macronutrients["carbs"] * snack_ratio) / snacks_count,
        fats=(macronutrients["fats"] * snack_ratio) / snacks_count,
        fiber=(micronutrients["fiber"] * snack_ratio) / snacks_count,
        calcium=(micronutrients["calcium"] * snack_ratio) / snacks_count,
        iron=(micronutrients["iron"] * snack_ratio) / snacks_count,
        zinc=(micronutrients["zinc"] * snack_ratio) / snacks_count,
        magnesium=(micronutrients["magnesium"] * snack_ratio) / snacks_count,
    )

    return PatientDietPlanBase(
        total_calories=tdee,
        protein=macronutrients["protein"],
        carbs=macronutrients["carbs"],
        fats=macronutrients["fats"],
        fiber=micronutrients["fiber"],
        calcium=micronutrients["calcium"],
        iron=micronutrients["iron"],
        zinc=micronutrients["zinc"],
        magnesium=micronutrients["magnesium"],
        major_meal=major_meal_distribution,
        snack=snack_distribution,
    )
