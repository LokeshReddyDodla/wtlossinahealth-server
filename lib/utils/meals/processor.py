from collections import defaultdict
from datetime import date, datetime, timedelta
from functools import partial
from statistics import median

from lib.core.postgres_store import PostgresStore

from lib.utils.date.periods import WeekWisePeriod
from lib.utils.cgm.summary import CGMSummaryStatsFetcher
from lib.utils.meals.daily_stats import build_daily_stats, empty_daily_stats
from lib.utils.meals.diet_recommendations import get_diet_recommendations
from lib.utils.meals.query_builders import (
    build_meal_query,
)
from lib.utils.postgres_session_decorator import with_postgres_session


class MealStatsProcessor:
    def __init__(
        self,
        postgres_store: PostgresStore,
        clickhouse_store,
        cgm_stats_processor,
        patient_profile_service,
        patient_plan_service,
        meal_report_service,
    ):
        self.postgres_store = postgres_store
        self.clickhouse_store = clickhouse_store
        self.patient_profile_service = patient_profile_service
        self.patient_plan_service = patient_plan_service
        self.cgm_stats_processor = cgm_stats_processor
        self.meal_report_service = meal_report_service

        self.get_diet_recommendation = partial(
            get_diet_recommendations,
            patient_plan_service=self.patient_plan_service,
            patient_profile_service=self.patient_profile_service,
        )

    @with_postgres_session
    async def get_meal_report_by_date(
        self, patient_id: str, date: date, *, postgres_session
    ):
        diet_recommendations = await self.get_diet_recommendation(
            patient_id,
            date,
        )

        # Fetch average glucose for the single date
        avg_glucose = CGMSummaryStatsFetcher.fetch_daily_average_glucose(
            self.clickhouse_store, patient_id, date, date
        ).get(date, 0.0)

        query = build_meal_query(patient_id, date, date)
        result = await postgres_session.execute(query)
        row = result.first()

        if not row:
            return empty_daily_stats(
                date, {date: avg_glucose}, diet_recommendations
            )

        return build_daily_stats(
            row,
            {date: avg_glucose},
            diet_recommendations,
            patient_id,
            self.cgm_stats_processor,
        )

    @with_postgres_session
    async def get_meal_report_by_date_range(
        self,
        patient_id: str,
        start_date: datetime,
        end_date: datetime,
        *,
        postgres_session,
    ):
        diet_recommendations = await self.get_diet_recommendation(
            patient_id,
            start_date,
        )

        # Fetch all glucose stats once for the entire date range
        avg_glucose_by_date = (
            CGMSummaryStatsFetcher.fetch_daily_average_glucose(
                self.clickhouse_store, patient_id, start_date, end_date
            )
        )

        query = build_meal_query(patient_id, start_date, end_date)
        result = await postgres_session.execute(query)
        rows = result.all()

        if not rows:
            return [
                empty_daily_stats(
                    start_date, avg_glucose_by_date, diet_recommendations
                )
            ]

        return [
            build_daily_stats(
                row,
                avg_glucose_by_date,
                diet_recommendations,
                patient_id,
                self.cgm_stats_processor,
            )
            for row in rows
        ]

    async def get_meal_statistics_in_range(
        self, patient_id: str, start_date: date, end_date: date
    ) -> dict:
        reports = await self.meal_report_service.fetch_daily_reports_in_range(
            patient_id, start_date, end_date
        )

        if not reports:
            return {}

        total_meals = 0
        high_carb_meals = 0
        low_protein_meals = 0
        low_fiber_meals = 0

        within_carb_range = 0
        within_protein_range = 0
        within_fat_budget = 0
        within_fiber_budget = 0

        meal_type_stats = defaultdict(
            lambda: {"carbs": [], "proteins": [], "fats": [], "fiber": []}
        )

        # thresholds (tune as needed or fetch from diet plan)
        HIGH_CARB_THRESHOLD = 60
        LOW_PROTEIN_THRESHOLD = 10
        LOW_FIBER_THRESHOLD = 3

        CARB_MIN, CARB_MAX = 45, 65
        PROTEIN_MIN, PROTEIN_MAX = 15, 40
        FAT_MIN, FAT_MAX = 20, 35
        FIBER_MIN, FIBER_MAX = 8, 15

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

        # build stats per meal type
        detailed_stats = {}
        for meal_type, nutrients in meal_type_stats.items():
            detailed_stats[meal_type] = {}
            for nutrient, values in nutrients.items():
                if not values:
                    continue
                nums = [v[0] for v in values]
                max_val, max_date = max(values, key=lambda x: x[0])
                detailed_stats[meal_type][nutrient] = {
                    "median": median(nums),
                    "range": [min(nums), max(nums)],
                    "max_value": max_val,
                    "max_date": max_date,
                }

        return {
            "total_meals": total_meals,
            "high_carb_meals": high_carb_meals,
            "low_protein_meals": low_protein_meals,
            "low_fiber_meals": low_fiber_meals,
            "within_carb_range_pct": (
                round(within_carb_range * 100 / total_meals, 1)
                if total_meals
                else 0.0
            ),
            "within_protein_range_pct": (
                round(within_protein_range * 100 / total_meals, 1)
                if total_meals
                else 0.0
            ),
            "within_fat_budget_pct": (
                round(within_fat_budget * 100 / total_meals, 1)
                if total_meals
                else 0.0
            ),
            "within_fiber_budget_pct": (
                round(within_fiber_budget * 100 / total_meals, 1)
                if total_meals
                else 0.0
            ),
            "meal_type_stats": detailed_stats,
        }

    async def get_meal_month_summary(
        self,
        patient_id: str,
        start_date: datetime,
        end_date: datetime,
    ) -> dict:
        reports = await self.meal_report_service.fetch_daily_reports_in_range(
            patient_id, start_date, end_date
        )
        if not reports:
            return {}

        # ---- Counters ----
        total_meals = 0
        snacks_count = 0
        meal_type_counts = {"breakfast": 0, "lunch": 0, "dinner": 0}
        high_carb_count = 0
        low_protein_count = 0

        # ---- Within-budget counters ----
        within_carb_range = 0
        within_protein_range = 0
        within_fat_range = 0
        within_fiber_range = 0

        # thresholds (can also come from diet recommendations)
        HIGH_CARB_THRESHOLD = 60
        LOW_PROTEIN_THRESHOLD = 10

        CARB_MIN, CARB_MAX = 45, 65
        PROTEIN_MIN, PROTEIN_MAX = 15, 40
        FAT_MIN, FAT_MAX = 20, 35
        FIBER_MIN, FIBER_MAX = 8, 15

        # ---- Weekly breakdowns (init buckets from split_into_weeks) ----
        week_periods = WeekWisePeriod(start_date, end_date).periods
        week_buckets = {
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

        # ---- Collect all meals ----
        for report in reports:
            rdate = datetime.fromisoformat(report["date"])
            for week in week_periods:
                if week["start_date"] <= rdate <= week["end_date"]:
                    bucket = week_buckets[week["week_no"]]
                    for meal in report.get("meals", []):
                        total_meals += 1
                        mtype = (meal.get("type") or "").lower()
                        macros = meal.get("total_macro_nutritional_value", {})
                        carbs = macros.get("carbohydrates") or 0
                        protein = macros.get("proteins") or 0
                        fat = macros.get("fats") or 0
                        fiber = macros.get("fiber") or 0

                        # Count meal types
                        if mtype == "snack":
                            snacks_count += 1
                        elif mtype in meal_type_counts:
                            meal_type_counts[mtype] += 1

                        # High/low checks
                        if carbs > HIGH_CARB_THRESHOLD:
                            high_carb_count += 1
                        if protein < LOW_PROTEIN_THRESHOLD:
                            low_protein_count += 1

                        # Within budget checks
                        if CARB_MIN <= carbs <= CARB_MAX:
                            within_carb_range += 1
                        if PROTEIN_MIN <= protein <= PROTEIN_MAX:
                            within_protein_range += 1
                        if FAT_MIN <= fat <= FAT_MAX:
                            within_fat_range += 1
                        if FIBER_MIN <= fiber <= FIBER_MAX:
                            within_fiber_range += 1

                        # Add to week bucket
                        bucket["carbs"].append(carbs)
                        bucket["proteins"].append(protein)
                        bucket["fats"].append(fat)
                        bucket["fiber"].append(fiber)
                    break

        # ---- Weekly summaries ----
        weekly = []
        for week_no, vals in week_buckets.items():
            carb_energy = sum(vals["carbs"]) * 4
            protein_energy = sum(vals["proteins"]) * 4
            fat_energy = sum(vals["fats"]) * 9
            total_energy = carb_energy + protein_energy + fat_energy or 1

            weekly.append(
                {
                    "week_label": f"Week {week_no}",
                    "iso_week_no": str(vals["iso_week_no"]),
                    "start_date": str(vals["start_date"]),
                    "end_date": str(vals["end_date"]),
                    "median_carbs": (
                        median(vals["carbs"]) if vals["carbs"] else 0
                    ),
                    "energy_pct": {
                        "carbs": round(carb_energy / total_energy * 100, 1),
                        "protein": round(
                            protein_energy / total_energy * 100, 1
                        ),
                        "fat": round(fat_energy / total_energy * 100, 1),
                    },
                }
            )

        # ---- Month vs previous month medians ----
        def compute_meal_type_medians(rpts):
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
            for rpt in rpts:
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
                mtype: {
                    macro: median(vals) if vals else 0
                    for macro, vals in macros.items()
                }
                for mtype, macros in buckets.items()
            }

        # previous month window
        first_of_current = start_date.replace(day=1)
        prev_month_last_day = first_of_current - timedelta(days=1)
        prev_start = prev_month_last_day.replace(day=1)
        prev_end = prev_month_last_day

        prev_reports = (
            await self.meal_report_service.fetch_daily_reports_in_range(
                patient_id, prev_start, prev_end
            )
        )

        current_type_medians = compute_meal_type_medians(reports)
        prev_type_medians = compute_meal_type_medians(prev_reports)

        meal_type_medians_month_compare = {
            mtype: {
                "current": current_type_medians.get(mtype, {}),
                "previous": prev_type_medians.get(mtype, {}),
            }
            for mtype in ("breakfast", "lunch", "dinner")
        }

        # ---- Return summary ----
        return {
            "counts": {
                "total_meals": total_meals,
                "snacks": snacks_count,
                **meal_type_counts,
                "high_carb_meals": high_carb_count,
                "low_protein_meals": low_protein_count,
            },
            "weekly": weekly,
            "within_budget_pct": {
                "carbs": (
                    round(within_carb_range * 100 / total_meals, 1)
                    if total_meals
                    else 0.0
                ),
                "protein": (
                    round(within_protein_range * 100 / total_meals, 1)
                    if total_meals
                    else 0.0
                ),
                "fat": (
                    round(within_fat_range * 100 / total_meals, 1)
                    if total_meals
                    else 0.0
                ),
                "fiber": (
                    round(within_fiber_range * 100 / total_meals, 1)
                    if total_meals
                    else 0.0
                ),
            },
            "meal_type_medians_month_compare": meal_type_medians_month_compare,
        }
