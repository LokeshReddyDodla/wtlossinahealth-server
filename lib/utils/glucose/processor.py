from datetime import datetime
from typing import Any, Dict, List

from lib.schemas.glucose_stats import GlucoseLevelStats, GlucoseReading
from lib.schemas.patient_meal import PatientMeal as PatientMealSchema
from lib.utils.date.periods import DayWisePeriod, WeekWisePeriod
from lib.utils.fitness.processor import FitnessStatsProcessor
from lib.utils.glucose.hyper_stats_fetcher import HyperStatsFetcher
from lib.utils.glucose.hypo_stats_fetcher import HypoStatsFetcher
from lib.utils.glucose.queries import (
    generate_avg_glucose_readings_by_hour_query,
    generate_glucose_readings_around_meal_query,
    generate_glucose_readings_by_date_query)
from lib.utils.glucose.range import GlucoseRangeStatsFetcher
from lib.utils.glucose.summary import GlucoseSummaryStatsFetcher
from lib.utils.glucose.time_period import GlucoseTimePeriodStatsFetcher


class GlucoseStatsProcessor:
    def __init__(
        self,
        clickhouse_store,
        meal_service,
        fitness_stats_processor: FitnessStatsProcessor,
    ):
        self.clickhouse_store = clickhouse_store
        self.meal_service = meal_service
        self.fitness_stats_processor = fitness_stats_processor

    def fetch_glucose_readings_by_date(
        self,
        patient_id: str,
        from_date_str: str,
        to_date_str: str,
    ) -> List[GlucoseReading]:
        query = generate_glucose_readings_by_date_query(
            patient_id, from_date_str, to_date_str
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
        self, patient_id: str, from_date_str: str, to_date_str: str
    ) -> List[GlucoseReading]:
        query = generate_avg_glucose_readings_by_hour_query(
            patient_id, from_date_str, to_date_str
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
        self,
        patient_id: str,
        meal_time: datetime,
        before_minutes=15,
        after_minutes=90,
    ):
        """Fetch glucose readings around the meal time."""
        query = generate_glucose_readings_around_meal_query(
            patient_id,
            meal_time.strftime("%Y-%m-%d %H:%M:%S"),
            before_minutes,
            after_minutes,
        )
        results = self.clickhouse_store.client.execute(query)

        glucose_before = [r for r in results if r[0] < meal_time]
        glucose_after = [r for r in results if r[0] >= meal_time]
        return glucose_before, glucose_after

    async def generate_report(
        self,
        patient_id: str,
        from_date: datetime,
        to_date: datetime,
    ) -> Dict[str, Any]:
        stats = {}

        # Overall Stats
        stats["overall"] = await self._process_period(
            patient_id,
            from_date,
            to_date,
        )

        # Day-wise Stats
        day_periods = DayWisePeriod(from_date, to_date).periods
        stats["day_wise"] = await self._process_multiple_periods(
            patient_id, day_periods, include_readings=True, include_meals=True
        )

        # # Week-wise Stats
        week_periods = WeekWisePeriod(from_date, to_date).periods
        stats["week_wise"] = await self._process_multiple_periods(
            patient_id,
            week_periods,
        )

        return stats

    async def _process_period(
        self,
        patient_id: str,
        from_date: datetime,
        to_date: datetime,
        include_readings: bool = False,
        include_meals: bool = False,
    ) -> GlucoseLevelStats:
        from_date_str = from_date.strftime("%Y-%m-%dT%H:%M:%S")
        to_date_str = to_date.strftime("%Y-%m-%dT%H:%M:%S")

        glucose_summary_stats = GlucoseSummaryStatsFetcher.fetch(
            self.clickhouse_store, patient_id, from_date_str, to_date_str
        )
        glucose_range_stats = GlucoseRangeStatsFetcher.fetch(
            self.clickhouse_store, patient_id, from_date_str, to_date_str
        )
        hyper_stats = HyperStatsFetcher().fetch(
            self.clickhouse_store, patient_id, from_date_str, to_date_str
        )
        hypo_stats = HypoStatsFetcher().fetch(
            self.clickhouse_store, patient_id, from_date_str, to_date_str
        )
        time_period_stats = GlucoseTimePeriodStatsFetcher.fetch(
            self.clickhouse_store, patient_id, from_date_str, to_date_str
        )

        fitness_report = self.fitness_stats_processor.fetch_summary_stats(
            patient_id, from_date_str, to_date_str
        )

        glucose_readings = None
        if include_readings:
            glucose_readings = self.fetch_glucose_readings_by_date(
                patient_id, from_date_str, to_date_str
            )

        meals = None
        if include_meals:
            meals = await self.meal_service.fetch_meals(
                patient_id=patient_id,
                from_datetime=from_date,
                to_datetime=to_date,
            )
            meals = [PatientMealSchema.from_orm(meal) for meal in meals]

        return GlucoseLevelStats(
            from_date=from_date,
            to_date=to_date,
            glucose_readings=glucose_readings,
            glucose_summary_stats=glucose_summary_stats,
            glucose_range_stats=glucose_range_stats,
            hyper_stats=hyper_stats,
            hypo_stats=hypo_stats,
            time_period_stats=time_period_stats,
            fitness_report=fitness_report,
            meals=meals,
        )

    async def _process_multiple_periods(
        self,
        patient_id: str,
        periods: List[Dict[str, datetime]],
        include_readings: bool = False,
        include_meals: bool = False,
    ) -> List[GlucoseLevelStats]:
        stats = []
        for period in periods:
            stats.append(
                await self._process_period(
                    patient_id,
                    period["from_date"],
                    period["to_date"],
                    include_readings=include_readings,
                    include_meals=include_meals,
                )
            )
        return stats
