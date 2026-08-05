"""Daily meal statistics builders."""

from datetime import datetime

from dateutil.parser import parse as parse_date

from lib.schemas.meal_stats import DailyMealStats


def compute_glucose_response(meal_time, glucose_before, glucose_after):
    """Summarize the post-meal glucose excursion from the raw CGM readings
    around a meal. `glucose_before`/`glucose_after` are lists of (time, glucose)
    rows. Returns None when there is no post-meal reading to measure against.

    Baseline is the reading just before the meal (falls back to the first
    post-meal reading); the excursion is peak-minus-baseline.
    """
    if not glucose_after:
        return None
    baseline = round(
        (glucose_before[-1][1] if glucose_before else glucose_after[0][1]), 1
    )
    peak_time, peak = max(glucose_after, key=lambda r: r[1])
    peak = round(peak, 1)
    # Returned to within 15 mg/dL of baseline at any point after the peak.
    returned = any(g <= baseline + 15 for t, g in glucose_after if t > peak_time)
    return {
        "baseline_mgdl": baseline,
        "peak_mgdl": peak,
        "delta_mgdl": round(peak - baseline, 1),
        "time_to_peak_minutes": round(
            (peak_time - meal_time).total_seconds() / 60, 1
        ),
        "returned_to_baseline": returned,
    }


def compute_glucose_comparison(prediction, response):
    """Predicted vs actual glucose, aligned by the prediction's ``basis`` so a
    rise is never compared to an absolute peak. Returns None unless both a
    prediction and a measured response exist.

    - basis="rise": predicted rise band vs actual delta.
    - basis="absolute": predicted peak band vs actual peak.
    """
    if not prediction or not response:
        return None
    basis = prediction.get("basis", "absolute")
    if basis == "rise":
        low = prediction.get("rise_mg_dl_low", prediction.get("range_mg_dl_low"))
        high = prediction.get("rise_mg_dl_high", prediction.get("range_mg_dl_high"))
        actual = response.get("delta_mgdl")
    else:
        low = prediction.get("range_mg_dl_low")
        high = prediction.get("range_mg_dl_high")
        actual = response.get("peak_mgdl")
    if low is None or high is None or actual is None:
        return None
    outcome = "within" if low <= actual <= high else ("above" if actual > high else "below")
    return {
        "basis": basis,
        "predicted_low": low,
        "predicted_high": high,
        "actual_mgdl": actual,
        "outcome": outcome,
    }


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
        meal["glucose_response"] = compute_glucose_response(
            meal_time, glucose_before_meal, glucose_after_meal
        )
        prediction = (meal.get("meal_analysis") or {}).get("predicted_glucose")
        meal["glucose_comparison"] = compute_glucose_comparison(
            prediction, meal["glucose_response"]
        )

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
