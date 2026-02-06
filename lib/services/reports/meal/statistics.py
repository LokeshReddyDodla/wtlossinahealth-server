"""Statistics calculation utilities for meal data."""

from collections import defaultdict
from datetime import date, datetime
from statistics import median
from typing import Dict, List, Tuple

from lib.schemas.meal_statistics import (
    MealTypeMedians,
    MealTypeNutrientStats,
    NutrientStats,
    WeeklyEnergyDistribution,
    WeeklyPeriod,
    WeeklySummary,
)
from .constants import (
    CARB_ENERGY_PER_GRAM,
    CARB_MAX,
    CARB_MIN,
    FAT_ENERGY_PER_GRAM,
    FAT_MAX,
    FAT_MIN,
    FIBER_MAX,
    FIBER_MIN,
    HIGH_CARB_THRESHOLD,
    LOW_FIBER_THRESHOLD,
    LOW_PROTEIN_THRESHOLD,
    PROTEIN_ENERGY_PER_GRAM,
    PROTEIN_MAX,
    PROTEIN_MIN,
)


class MealStatistics:
    """Statistics calculation utilities for meal data."""

    @staticmethod
    def calculate_meal_counts_and_budget_compliance(
        reports: List[Dict],
    ) -> Tuple[int, int, int, int, int, int, int, int]:
        """Calculate meal counts and budget compliance metrics."""
        total_meals = 0
        high_carb_meals = 0
        low_protein_meals = 0
        low_fiber_meals = 0

        within_carb_range = 0
        within_protein_range = 0
        within_fat_budget = 0
        within_fiber_budget = 0

        for report in reports:
            for meal in report.get("meals", []):
                total_meals += 1

                macros = meal.get("total_macro_nutritional_value", {})
                carbs = macros.get("carbohydrates") or 0
                proteins = macros.get("proteins") or 0
                fats = macros.get("fats") or 0
                fiber = macros.get("fiber") or 0

                if carbs > HIGH_CARB_THRESHOLD:
                    high_carb_meals += 1
                if proteins < LOW_PROTEIN_THRESHOLD:
                    low_protein_meals += 1
                if fiber < LOW_FIBER_THRESHOLD:
                    low_fiber_meals += 1

                if CARB_MIN <= carbs <= CARB_MAX:
                    within_carb_range += 1
                if PROTEIN_MIN <= proteins <= PROTEIN_MAX:
                    within_protein_range += 1
                if FAT_MIN <= fats <= FAT_MAX:
                    within_fat_budget += 1
                if FIBER_MIN <= fiber <= FIBER_MAX:
                    within_fiber_budget += 1

        return (
            total_meals,
            high_carb_meals,
            low_protein_meals,
            low_fiber_meals,
            within_carb_range,
            within_protein_range,
            within_fat_budget,
            within_fiber_budget,
        )

    @staticmethod
    def collect_meal_type_stats(reports: List[Dict]) -> Dict[str, Dict[str, List[Tuple[float, str]]]]:
        """Collect statistics grouped by meal type."""
        meal_type_stats = defaultdict(
            lambda: {"carbs": [], "proteins": [], "fats": [], "fiber": []}
        )

        for report in reports:
            for meal in report.get("meals", []):
                macros = meal.get("total_macro_nutritional_value", {})
                carbs = macros.get("carbohydrates") or 0
                proteins = macros.get("proteins") or 0
                fats = macros.get("fats") or 0
                fiber = macros.get("fiber") or 0

                meal_type = meal.get("type", "other").lower()
                meal_type_stats[meal_type]["carbs"].append(
                    (carbs, report["date"])
                )
                meal_type_stats[meal_type]["proteins"].append(
                    (proteins, report["date"])
                )
                meal_type_stats[meal_type]["fats"].append(
                    (fats, report["date"])
                )
                meal_type_stats[meal_type]["fiber"].append(
                    (fiber, report["date"])
                )

        return meal_type_stats

    @staticmethod
    def calculate_meal_type_nutrient_stats(
        meal_type_stats: Dict[str, Dict[str, List[Tuple[float, str]]]]
    ) -> Dict[str, MealTypeNutrientStats]:
        """Calculate nutrient statistics for each meal type."""
        detailed_stats = {}
        for meal_type, nutrients in meal_type_stats.items():
            meal_type_nutrients = {}
            for nutrient, values in nutrients.items():
                if not values:
                    continue
                nums = [v[0] for v in values]
                max_val, max_date_str = max(values, key=lambda x: x[0])
                max_date = datetime.fromisoformat(max_date_str).date()
                meal_type_nutrients[nutrient] = NutrientStats(
                    median=median(nums),
                    range=[min(nums), max(nums)],
                    max_value=max_val,
                    max_date=max_date,
                )
            if meal_type_nutrients:
                detailed_stats[meal_type] = MealTypeNutrientStats(
                    carbs=meal_type_nutrients.get("carbs"),
                    proteins=meal_type_nutrients.get("proteins"),
                    fats=meal_type_nutrients.get("fats"),
                    fiber=meal_type_nutrients.get("fiber"),
                )
        return detailed_stats

    @staticmethod
    def calculate_weekly_summaries(
        week_buckets: Dict[str, Dict],
        week_periods: List[Dict],
    ) -> List[WeeklySummary]:
        """Calculate weekly summaries from week buckets."""
        weekly_summaries = []
        for week in week_periods:
            week_no = week["week_no"]
            vals = week_buckets[week_no]

            carb_energy = sum(vals["carbs"]) * CARB_ENERGY_PER_GRAM
            protein_energy = sum(vals["proteins"]) * PROTEIN_ENERGY_PER_GRAM
            fat_energy = sum(vals["fats"]) * FAT_ENERGY_PER_GRAM
            total_energy = carb_energy + protein_energy + fat_energy or 1

            weekly_summaries.append(
                WeeklySummary(
                    period=WeeklyPeriod(
                        week_label=f"Week {week_no}",
                        iso_week_no=str(vals["iso_week_no"]),
                        start_date=str(vals["start_date"]),
                        end_date=str(vals["end_date"]),
                    ),
                    median_carbs=median(vals["carbs"]) if vals["carbs"] else 0,
                    energy_distribution=WeeklyEnergyDistribution(
                        carbs=round(carb_energy / total_energy * 100, 1),
                        protein=round(protein_energy / total_energy * 100, 1),
                        fat=round(fat_energy / total_energy * 100, 1),
                    ),
                )
            )
        return weekly_summaries

    @staticmethod
    def compute_meal_type_medians(reports: List[Dict]) -> Dict[str, MealTypeMedians]:
        """Compute median nutrient values for each meal type."""
        buckets = {
            "breakfast": {
                "carbs": [],
                "protein": [],
                "fat": [],
                "fiber": [],
            },
            "lunch": {"carbs": [], "protein": [], "fat": [], "fiber": []},
            "dinner": {"carbs": [], "protein": [], "fat": [], "fiber": []},
        }
        for rpt in reports:
            for meal in rpt.get("meals", []):
                mtype = (meal.get("type") or "").lower()
                if mtype not in buckets:
                    continue
                macros = meal.get("total_macro_nutritional_value", {})
                buckets[mtype]["carbs"].append(
                    macros.get("carbohydrates") or 0
                )
                buckets[mtype]["protein"].append(macros.get("proteins") or 0)
                buckets[mtype]["fat"].append(macros.get("fats") or 0)
                buckets[mtype]["fiber"].append(macros.get("fiber") or 0)
        return {
            mtype: MealTypeMedians(
                carbs=median(buckets[mtype]["carbs"]) if buckets[mtype]["carbs"] else 0,
                protein=median(buckets[mtype]["protein"]) if buckets[mtype]["protein"] else 0,
                fat=median(buckets[mtype]["fat"]) if buckets[mtype]["fat"] else 0,
                fiber=median(buckets[mtype]["fiber"]) if buckets[mtype]["fiber"] else 0,
            )
            for mtype in buckets.keys()
        }

    @staticmethod
    def calculate_monthly_counts(
        reports: List[Dict],
    ) -> Tuple[int, int, Dict[str, int], int, int]:
        """Calculate monthly meal counts by type."""
        total_meals = 0
        snacks_count = 0
        meal_type_counts = {"breakfast": 0, "lunch": 0, "dinner": 0}
        high_carb_count = 0
        low_protein_count = 0

        for report in reports:
            for meal in report.get("meals", []):
                total_meals += 1
                mtype = (meal.get("type") or "").lower()
                macros = meal.get("total_macro_nutritional_value", {})
                carbs = macros.get("carbohydrates") or 0
                protein = macros.get("proteins") or 0

                if mtype == "snack":
                    snacks_count += 1
                elif mtype in meal_type_counts:
                    meal_type_counts[mtype] += 1

                if carbs > HIGH_CARB_THRESHOLD:
                    high_carb_count += 1
                if protein < LOW_PROTEIN_THRESHOLD:
                    low_protein_count += 1

        return (
            total_meals,
            snacks_count,
            meal_type_counts,
            high_carb_count,
            low_protein_count,
        )

    @staticmethod
    def calculate_monthly_budget_compliance(
        reports: List[Dict],
    ) -> Tuple[int, int, int, int]:
        """Calculate monthly budget compliance metrics."""
        within_carb_range = 0
        within_protein_range = 0
        within_fat_range = 0
        within_fiber_range = 0

        for report in reports:
            for meal in report.get("meals", []):
                macros = meal.get("total_macro_nutritional_value", {})
                carbs = macros.get("carbohydrates") or 0
                protein = macros.get("proteins") or 0
                fat = macros.get("fats") or 0
                fiber = macros.get("fiber") or 0

                if CARB_MIN <= carbs <= CARB_MAX:
                    within_carb_range += 1
                if PROTEIN_MIN <= protein <= PROTEIN_MAX:
                    within_protein_range += 1
                if FAT_MIN <= fat <= FAT_MAX:
                    within_fat_range += 1
                if FIBER_MIN <= fiber <= FIBER_MAX:
                    within_fiber_range += 1

        return (
            within_carb_range,
            within_protein_range,
            within_fat_range,
            within_fiber_range,
        )

    @staticmethod
    def build_week_buckets(
        week_periods: List[Dict],
    ) -> Dict[str, Dict]:
        """Build week buckets for aggregating meal data."""
        return {
            week["week_no"]: {
                "start_date": week["start_date"].date(),
                "end_date": week["end_date"].date(),
                "iso_week_no": week["iso_week_no"],
                "carbs": [],
                "proteins": [],
                "fats": [],
                "fiber": [],
            }
            for week in week_periods
        }

    @staticmethod
    def populate_week_buckets(
        reports: List[Dict],
        week_periods: List[Dict],
        week_buckets: Dict[str, Dict],
    ) -> None:
        """Populate week buckets with meal data."""
        for report in reports:
            rdate = datetime.fromisoformat(report["date"])
            for week in week_periods:
                if week["start_date"] <= rdate <= week["end_date"]:
                    bucket = week_buckets[week["week_no"]]
                    for meal in report.get("meals", []):
                        macros = meal.get("total_macro_nutritional_value", {})
                        bucket["carbs"].append(macros.get("carbohydrates") or 0)
                        bucket["proteins"].append(macros.get("proteins") or 0)
                        bucket["fats"].append(macros.get("fats") or 0)
                        bucket["fiber"].append(macros.get("fiber") or 0)
                    break
