from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from lib.models.patient import Patient
from lib.models.patient_connected_app import PatientConnectedApp
from lib.models.patient_eating_habit import \
    PatientEatingHabit as PatientEatingHabitModel
from lib.models.patient_meal import PatientFoodItem
from lib.models.patient_meal import PatientMeal as PatientMealModel
from lib.schemas.glucose_stats import GlucoseLevelStats, GlucoseReading
from lib.schemas.patient import CompletePatientProfile
from lib.schemas.patient_meal import PatientMeal as PatientMealSchema
from lib.services.meal_service import MealService
from lib.utils.glucose.hyper_stats_fetcher import HyperStatsFetcher
from lib.utils.glucose.hypo_stats_fetcher import HypoStatsFetcher
from lib.utils.glucose.queries import (
    generate_avg_glucose_readings_by_hour_query,
    generate_glucose_readings_around_meal_query,
    generate_glucose_readings_by_date_query)
from lib.utils.glucose.range import GlucoseRangeStatsFetcher
from lib.utils.glucose.summary import GlucoseSummaryStatsFetcher


class GlucoseStatsProcessor:
    def __init__(
        self,
        clickhouse_store,
        postgres_session,
        meal_service: MealService,
        patient_id,
    ):
        self.clickhouse_store = clickhouse_store
        self.postgres_session = postgres_session
        self.meal_service = meal_service
        self.patient_id = patient_id

    def fetch_glucose_readings_by_date(
        self, from_date_str: str, to_date_str: str
    ) -> List[GlucoseReading]:
        query = generate_glucose_readings_by_date_query(
            self.patient_id, from_date_str, to_date_str
        )
        data = self.clickhouse_store.client.execute(query)
        if not data:
            return []

        readings = [
            GlucoseReading(Device_Timestamp=row[0], Glucose_Level=row[1])
            for row in data
        ]
        return readings

    def fetch_avg_glucose_readings_by_hour(
        self, from_date_str: str, to_date_str: str
    ) -> List[GlucoseReading]:
        query = generate_avg_glucose_readings_by_hour_query(
            self.patient_id, from_date_str, to_date_str
        )
        data = self.clickhouse_store.client.execute(query)
        if not data:
            return []

        grouped = [
            GlucoseReading(Device_Timestamp=row[0], Glucose_Level=row[1])
            for row in data
        ]
        return grouped

    def fetch_glucose_around_meal(
        self, meal_time: datetime, before_minutes=15, after_minutes=90
    ):
        """Fetch glucose readings around the meal time."""
        query = generate_glucose_readings_around_meal_query(
            self.patient_id,
            meal_time.strftime("%Y-%m-%d %H:%M:%S"),
            before_minutes,
            after_minutes,
        )
        results = self.clickhouse_store.client.execute(query)

        glucose_before = [r for r in results if r[0] < meal_time]
        glucose_after = [r for r in results if r[0] >= meal_time]
        return glucose_before, glucose_after

    async def process(
        self, periods: List[Dict[str, datetime]], include_readings=False
    ) -> Dict[str, GlucoseLevelStats]:
        stats = {}

        for period in periods:
            from_date = period["from_date"]
            to_date = period["to_date"]
            from_date_str = from_date.strftime("%Y-%m-%dT%H:%M:%S")
            to_date_str = to_date.strftime("%Y-%m-%dT%H:%M:%S")

            glucose_summary_stats = GlucoseSummaryStatsFetcher.fetch(
                self.clickhouse_store,
                self.patient_id,
                from_date_str,
                to_date_str,
            )

            glucose_range_stats = GlucoseRangeStatsFetcher.fetch(
                self.clickhouse_store,
                self.patient_id,
                from_date_str,
                to_date_str,
            )

            hyper_stats = HyperStatsFetcher().fetch(
                self.clickhouse_store,
                self.patient_id,
                from_date_str,
                to_date_str,
            )

            hypo_stats = HypoStatsFetcher().fetch(
                self.clickhouse_store,
                self.patient_id,
                from_date_str,
                to_date_str,
            )

            glucose_readings = None
            meals = None

            if "date" in period:
                period_key = period["date"]
                if include_readings:
                    glucose_readings = self.fetch_glucose_readings_by_date(
                        from_date_str, to_date_str
                    )
                    meals = await self.meal_service.fetch_meals(
                        from_datetime=from_date,
                        to_datetime=to_date,
                        patient_id=self.patient_id,
                    )

                    meals = [
                        PatientMealSchema.from_orm(meal) for meal in meals
                    ]

            elif "week_no" in period:
                period_key = f"Week {period['week_no']}"
                if include_readings:
                    glucose_readings = self.fetch_avg_glucose_readings_by_hour(
                        from_date_str, to_date_str
                    )

            else:
                period_key = "overall"

            stats[period_key] = GlucoseLevelStats(
                from_date=from_date,
                to_date=to_date,
                glucose_readings=glucose_readings,
                meals=meals,
                glucose_summary_stats=glucose_summary_stats,
                glucose_range_stats=glucose_range_stats,
                hyper_stats=hyper_stats,
                hypo_stats=hypo_stats,
            )
        return stats
