import asyncio
from datetime import date, datetime, timedelta, time
from functools import partial

from lib.schemas.meal_statistics import (
    DateRange,
    DailyMeals,
    GlucoseImpactMeal,
    MealComparisonDeltas,
    MealCounts,
    MealStatisticsComparison,
    MealStatisticsReport,
    MealStatisticsSummary,
    MealTypeBreakdown,
    MealTypeComparison,
    MealTypeMedians,
    MealsData,
    MonthlyMealCounts,
    MonthlySummary,
    ReportMetadata,
    WithinBudgetPercentages,
)
from lib.utils.date.periods import WeekWisePeriod
from lib.services.reports.cgm.statistics import CGMStatistics
from lib.utils.meals.diet_recommendations import get_diet_recommendations
from lib.utils.postgres_session_decorator import with_postgres_session

from .daily_stats import build_daily_stats, empty_daily_stats
from .queries import build_meal_query
from .statistics import MealStatistics


class MealStatsProcessor:
    def __init__(
        self,
        postgres_store,
        clickhouse_store,
        cgm_stats_processor,
        patient_diet_plan_service,
        meal_report_service,
    ):
        self.postgres_store = postgres_store
        self.clickhouse_store = clickhouse_store
        self.patient_diet_plan_service = patient_diet_plan_service
        self.cgm_stats_processor = cgm_stats_processor
        self.meal_report_service = meal_report_service

        self.get_diet_recommendation = partial(
            get_diet_recommendations,
            patient_diet_plan_service=self.patient_diet_plan_service,
        )

    @with_postgres_session
    async def get_meal_report_by_date(
        self, patient_id: str, date: date, *, postgres_session
    ):
        diet_recommendations = await self.get_diet_recommendation(
            patient_id,
            date,
        )

        start_dt = datetime.combine(date, time.min)
        end_dt = datetime.combine(date, time.max)

        avg_glucose = (
            await asyncio.to_thread(
                CGMStatistics.fetch_daily_average_glucose,
                self.clickhouse_store,
                patient_id,
                start_dt,
                end_dt,
            )
        ).get(date, 0.0)

        query = build_meal_query(patient_id, date, date)
        result = await postgres_session.execute(query)
        row = result.first()

        if not row:
            return empty_daily_stats(date, {date: avg_glucose}, diet_recommendations)

        day_readings = await asyncio.to_thread(
            self.cgm_stats_processor.get_readings_for_window,
            patient_id,
            start_dt - timedelta(minutes=30),
            end_dt + timedelta(minutes=90),
        )
        return build_daily_stats(
            row,
            {date: avg_glucose},
            diet_recommendations,
            day_readings,
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

        avg_glucose_by_date = await asyncio.to_thread(
            CGMStatistics.fetch_daily_average_glucose,
            self.clickhouse_store, patient_id, start_date, end_date,
        )

        query = build_meal_query(patient_id, start_date, end_date)
        result = await postgres_session.execute(query)
        rows = result.all()

        if not rows:
            return [
                empty_daily_stats(start_date, avg_glucose_by_date, diet_recommendations)
            ]

        readings = await asyncio.to_thread(
            self.cgm_stats_processor.get_readings_for_window,
            patient_id,
            datetime.combine(min(r.date for r in rows), time.min) - timedelta(minutes=30),
            datetime.combine(max(r.date for r in rows), time.max) + timedelta(minutes=90),
        )
        return [
            build_daily_stats(
                row,
                avg_glucose_by_date,
                diet_recommendations,
                readings,
            )
            for row in rows
        ]

    async def get_meal_statistics_in_range(
        self, patient_id: str, start_date: date, end_date: date
    ) -> MealStatisticsReport:
        reports = await self.meal_report_service.fetch_daily_reports_in_range(
            patient_id, start_date, end_date
        )

        days_covered = (end_date - start_date).days + 1

        (
            total_meals,
            high_carb_meals,
            low_protein_meals,
            low_fiber_meals,
            within_carb_range,
            within_protein_range,
            within_fat_budget,
            within_fiber_budget,
        ) = MealStatistics.calculate_meal_counts_and_budget_compliance(reports)

        meal_type_stats = MealStatistics.collect_meal_type_stats(reports)
        detailed_stats = MealStatistics.calculate_meal_type_nutrient_stats(
            meal_type_stats
        )

        meals_by_date = [
            DailyMeals(
                date=report["date"],
                meals=report.get("meals", []),
            )
            for report in reports
            if report.get("meals")
        ]

        if not reports:
            start_datetime = datetime.combine(start_date, datetime.min.time())
            end_datetime = datetime.combine(end_date, datetime.max.time())
            return MealStatisticsReport(
                metadata=ReportMetadata(
                    date_range=DateRange(
                        start=start_datetime.isoformat(),
                        end=end_datetime.isoformat(),
                    ),
                    total_meals=0,
                    days_covered=days_covered,
                ),
                summary=MealStatisticsSummary(
                    counts=MealCounts(
                        total_meals=0,
                        high_carb_meals=0,
                        low_protein_meals=0,
                        low_fiber_meals=0,
                    ),
                    within_budget_percentages=WithinBudgetPercentages(
                        carbs=0.0,
                        protein=0.0,
                        fat=0.0,
                        fiber=0.0,
                    ),
                ),
                breakdowns=MealTypeBreakdown(by_meal_type={}),
                meals=None,
            )

        def _pct(n: int) -> float:
            return round(n * 100 / total_meals, 1) if total_meals else 0.0

        current_pcts = WithinBudgetPercentages(
            carbs=_pct(within_carb_range),
            protein=_pct(within_protein_range),
            fat=_pct(within_fat_budget),
            fiber=_pct(within_fiber_budget),
        )

        # Compare against the immediately-preceding equal-length range.
        prev_end = start_date - timedelta(days=1)
        prev_start = prev_end - timedelta(days=days_covered - 1)
        prev_reports = await self.meal_report_service.fetch_daily_reports_in_range(
            patient_id, prev_start, prev_end
        )
        comparison = None
        if prev_reports:
            (
                prev_total, _hc, _lp, _lf,
                prev_carb, prev_prot, prev_fat, prev_fiber,
            ) = MealStatistics.calculate_meal_counts_and_budget_compliance(prev_reports)

            def _prev_pct(n: int) -> float:
                return round(n * 100 / prev_total, 1) if prev_total else 0.0

            comparison = MealStatisticsComparison(
                previous_range=DateRange(
                    start=datetime.combine(prev_start, datetime.min.time()).isoformat(),
                    end=datetime.combine(prev_end, datetime.max.time()).isoformat(),
                ),
                previous_total_meals=prev_total,
                deltas=MealComparisonDeltas(
                    total_meals=total_meals - prev_total,
                    within_budget_carbs=round(current_pcts.carbs - _prev_pct(prev_carb), 1),
                    within_budget_protein=round(current_pcts.protein - _prev_pct(prev_prot), 1),
                    within_budget_fat=round(current_pcts.fat - _prev_pct(prev_fat), 1),
                    within_budget_fiber=round(current_pcts.fiber - _prev_pct(prev_fiber), 1),
                ),
            )

        # Rank meals by measured glucose impact (only meals whose report was
        # generated after glucose_response shipped carry the field).
        impact = [
            GlucoseImpactMeal(
                date=report["date"],
                name=meal.get("name"),
                type=meal.get("slot"),
                delta_mgdl=resp["delta_mgdl"],
                peak_mgdl=resp.get("peak_mgdl", 0.0),
            )
            for report in reports
            for meal in report.get("meals", [])
            if (resp := meal.get("glucose_response") or {}).get("delta_mgdl") is not None
        ]
        impact.sort(key=lambda m: m.delta_mgdl, reverse=True)

        return MealStatisticsReport(
            metadata=ReportMetadata(
                date_range=DateRange(
                    start=datetime.combine(start_date, datetime.min.time()).isoformat(),
                    end=datetime.combine(end_date, datetime.max.time()).isoformat(),
                ),
                total_meals=total_meals,
                days_covered=days_covered,
            ),
            summary=MealStatisticsSummary(
                counts=MealCounts(
                    total_meals=total_meals,
                    high_carb_meals=high_carb_meals,
                    low_protein_meals=low_protein_meals,
                    low_fiber_meals=low_fiber_meals,
                ),
                within_budget_percentages=current_pcts,
            ),
            breakdowns=MealTypeBreakdown(by_meal_type=detailed_stats),
            meals=MealsData(by_date=meals_by_date) if meals_by_date else None,
            comparison=comparison,
            top_glucose_impact_meals=impact[:5] or None,
        )

    async def get_meal_month_summary(
        self,
        patient_id: str,
        start_date: datetime,
        end_date: datetime,
    ) -> MonthlySummary:
        reports = await self.meal_report_service.fetch_daily_reports_in_range(
            patient_id, start_date, end_date
        )

        days_covered = (end_date.date() - start_date.date()).days + 1
        start_datetime = datetime.combine(start_date.date(), datetime.min.time())
        end_datetime = datetime.combine(end_date.date(), datetime.max.time())

        (
            total_meals,
            snacks_count,
            meal_type_counts,
            high_carb_count,
            low_protein_count,
        ) = MealStatistics.calculate_monthly_counts(reports)

        (
            within_carb_range,
            within_protein_range,
            within_fat_range,
            within_fiber_range,
        ) = MealStatistics.calculate_monthly_budget_compliance(reports)

        week_periods = WeekWisePeriod(start_date, end_date).periods
        week_buckets = MealStatistics.build_week_buckets(week_periods)
        MealStatistics.populate_week_buckets(reports, week_periods, week_buckets)

        weekly_summaries = MealStatistics.calculate_weekly_summaries(
            week_buckets, week_periods
        )

        if not reports:
            return MonthlySummary(
                metadata=ReportMetadata(
                    date_range=DateRange(
                        start=start_datetime.isoformat(),
                        end=end_datetime.isoformat(),
                    ),
                    total_meals=0,
                    days_covered=days_covered,
                ),
                counts=MonthlyMealCounts(
                    total_meals=0,
                    snacks=0,
                    breakfast=0,
                    lunch=0,
                    dinner=0,
                    high_carb_meals=0,
                    low_protein_meals=0,
                ),
                within_budget_percentages=WithinBudgetPercentages(
                    carbs=0.0,
                    protein=0.0,
                    fat=0.0,
                    fiber=0.0,
                ),
                weekly_summaries=[],
                meal_type_comparison={},
            )

        first_of_current = start_date.replace(day=1)
        prev_month_last_day = first_of_current - timedelta(days=1)
        prev_start = prev_month_last_day.replace(day=1)
        prev_end = prev_month_last_day

        prev_reports = await self.meal_report_service.fetch_daily_reports_in_range(
            patient_id, prev_start, prev_end
        )

        current_type_medians = MealStatistics.compute_meal_type_medians(reports)
        prev_type_medians = MealStatistics.compute_meal_type_medians(prev_reports)

        meal_type_comparison = {
            mtype: MealTypeComparison(
                current=current_type_medians.get(
                    mtype,
                    MealTypeMedians(carbs=0, protein=0, fat=0, fiber=0),
                ),
                previous=prev_type_medians.get(
                    mtype,
                    MealTypeMedians(carbs=0, protein=0, fat=0, fiber=0),
                ),
            )
            for mtype in ("breakfast", "lunch", "dinner")
        }

        return MonthlySummary(
            metadata=ReportMetadata(
                date_range=DateRange(
                    start=start_datetime.isoformat(),
                    end=end_datetime.isoformat(),
                ),
                total_meals=total_meals,
                days_covered=days_covered,
            ),
            counts=MonthlyMealCounts(
                total_meals=total_meals,
                snacks=snacks_count,
                breakfast=meal_type_counts["breakfast"],
                lunch=meal_type_counts["lunch"],
                dinner=meal_type_counts["dinner"],
                high_carb_meals=high_carb_count,
                low_protein_meals=low_protein_count,
            ),
            within_budget_percentages=WithinBudgetPercentages(
                carbs=round(within_carb_range * 100 / total_meals, 1)
                if total_meals
                else 0.0,
                protein=round(within_protein_range * 100 / total_meals, 1)
                if total_meals
                else 0.0,
                fat=round(within_fat_range * 100 / total_meals, 1)
                if total_meals
                else 0.0,
                fiber=round(within_fiber_range * 100 / total_meals, 1)
                if total_meals
                else 0.0,
            ),
            weekly_summaries=weekly_summaries,
            meal_type_comparison=meal_type_comparison,
        )
