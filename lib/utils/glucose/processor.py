from datetime import datetime
from typing import Any, Dict, List
from sqlalchemy import select
from lib.models.meal import FoodItem, Meal
from lib.models.patient import Patient
from lib.models.patient_connected_app import PatientConnectedApp
from lib.schemas.patient import PatientDetail

from sqlalchemy.orm import selectinload
from lib.utils.glucose.hyper_stats_fetcher import HyperStatsFetcher
from lib.utils.glucose.hypo_stats_fetcher import HypoStatsFetcher
from lib.utils.glucose.queries import (
    generate_avg_glucose_readings_by_hour_query,
    generate_glucose_readings_by_date_query,
)
from lib.utils.glucose.range import GlucoseRangeStatsFetcher
from lib.utils.glucose.summary import GlucoseSummaryStatsFetcher
from lib.schemas.glucose import (
    GlucoseLevelStats,
    GlucoseReading,
)


class PeriodicStatsProcessor:
    def __init__(self, clickhouse_store, postgres_session, patient_id):
        self.clickhouse_store = clickhouse_store
        self.postgres_session = postgres_session
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

    async def fetch_meals(self, from_date, to_date):
        query = (
            select(Meal)
            .where(Meal.patient_id == self.patient_id)
            .filter(Meal.time >= from_date)
            .filter(Meal.time <= to_date)
            .options(
                selectinload(Meal.items).selectinload(
                    FoodItem.nutritional_values
                ),
                selectinload(Meal.total_nutritional_value),
            )
        )
        result = await self.postgres_session.execute(query)
        meals = result.scalars().all()
        return meals

    async def fetch_profile(self) -> PatientDetail:
        query = (
            select(Patient)
            .where(Patient.patient_id == self.patient_id)
            .options(
                selectinload(Patient.daily_activities),
                selectinload(Patient.food_allergies),
                selectinload(Patient.drug_allergies),
                selectinload(Patient.diet_preferences),
                selectinload(Patient.alcohol_consumption),
                selectinload(Patient.smoking_habits),
                selectinload(Patient.meal_timings),
                selectinload(Patient.cuisine_preferences),
                selectinload(Patient.sleep_summary),
                selectinload(Patient.diabetic_history),
                selectinload(Patient.family_diabetic_history),
                selectinload(Patient.medical_history),
                selectinload(Patient.current_medication),
                selectinload(Patient.connected_apps).selectinload(
                    PatientConnectedApp.libreview
                ),
                selectinload(Patient.connected_apps).selectinload(
                    PatientConnectedApp.other_app
                ),
            )
        )
        result = await self.postgres_session.execute(query)
        patient = result.scalars().first()
        patient_detail = PatientDetail.from_orm(patient)
        return patient_detail

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
                    meals = await self.fetch_meals(from_date, to_date)

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
