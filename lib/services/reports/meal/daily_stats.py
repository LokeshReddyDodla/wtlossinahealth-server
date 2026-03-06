"""Daily meal statistics builders."""

from datetime import datetime

from dateutil.parser import parse as parse_date

from lib.schemas.meal_stats import DailyMealStats


def empty_daily_stats(date, avg_glucose_by_date, diet_recommendations):
    """Create empty daily stats when no meal data is available."""
    return DailyMealStats(
        date=date,
        meal_count=0,
        meals=[],
        calories=0,
        proteins=0,
        carbohydrates=0,
        simple_carbs=0,
        complex_carbs=0,
        fats=0,
        fiber=0,
        calcium=0,
        iron=0,
        zinc=0,
        magnesium=0,
        avg_glucose=avg_glucose_by_date.get(date, 0.0),
        diet_recommendations=diet_recommendations,
    )


def build_daily_stats(
    row,
    avg_glucose_by_date,
    diet_recommendations,
    patient_id,
    cgm_stats_processor,
):
    """Build daily meal statistics from database row."""
    for meal in row.meals:
        meal_time = datetime.combine(row.date, parse_date(meal["time"]).time())
        glucose_before_meal, glucose_after_meal = (
            cgm_stats_processor.get_readings_around_meal(patient_id, meal_time)
        )

        meal["glucose_before_meal"] = glucose_before_meal
        meal["glucose_after_meal"] = glucose_after_meal

    return DailyMealStats(
        date=row.date,
        meal_count=row.meal_count,
        meals=row.meals,
        calories=row.calories or 0,
        proteins=row.proteins or 0,
        carbohydrates=row.carbohydrates or 0,
        simple_carbs=row.simple_carbs or 0,
        complex_carbs=row.complex_carbs or 0,
        fats=row.fats or 0,
        fiber=row.fiber or 0,
        calcium=row.calcium or 0,
        iron=row.iron or 0,
        zinc=row.zinc or 0,
        magnesium=row.magnesium or 0,
        avg_glucose=avg_glucose_by_date.get(row.date, 0.0),
        diet_recommendations=diet_recommendations,
    )
