import hashlib
from datetime import datetime
from typing import Any, Dict, List, Literal

from lib.schemas.glucose_stats import GlucoseLevelStats, GlucoseReading
from lib.services.meal_report_service import MealReportService
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

ReportTypeLiteral = Literal["daily", "weekly", "other"]


class GlucoseStatsProcessor:
    def __init__(
        self,
        clickhouse_store,
        meal_service,
        fitness_stats_processor: FitnessStatsProcessor,
        meal_report_service: MealReportService,
    ):
        self.clickhouse_store = clickhouse_store
        self.meal_service = meal_service
        self.fitness_stats_processor = fitness_stats_processor
        self.meal_report_service = meal_report_service

    def fetch_glucose_readings_by_date(
        self,
        patient_id: str,
        start_date_str: str,
        end_date_str: str,
    ) -> List[GlucoseReading]:
        query = generate_glucose_readings_by_date_query(
            patient_id, start_date_str, end_date_str
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
        self, patient_id: str, start_date_str: str, end_date_str: str
    ) -> List[GlucoseReading]:
        query = generate_avg_glucose_readings_by_hour_query(
            patient_id, start_date_str, end_date_str
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
        start_date: datetime,
        end_date: datetime,
    ) -> Dict[str, Any]:
        stats = {}

        # Overall Stats
        stats["overall"] = (
            await self._process_period(
                patient_id, start_date, end_date, "other"
            )
        ).model_dump()

        # Day-wise Stats
        day_periods = DayWisePeriod(start_date, end_date).periods
        stats["day_wise"] = [
            period.model_dump()
            for period in await self._process_multiple_periods(
                patient_id,
                day_periods,
                "daily",
            )
        ]

        # # Week-wise Stats
        week_periods = WeekWisePeriod(start_date, end_date).periods
        stats["week_wise"] = [
            period.model_dump()
            for period in await self._process_multiple_periods(
                patient_id, week_periods, "weekly"
            )
        ]

        return stats

    async def _process_period(
        self,
        patient_id: str,
        start_date: datetime,
        end_date: datetime,
        report_type: ReportTypeLiteral,
    ) -> GlucoseLevelStats:
        start_date_str = start_date.strftime("%Y-%m-%dT%H:%M:%S")
        end_date_str = end_date.strftime("%Y-%m-%dT%H:%M:%S")

        glucose_summary_stats = GlucoseSummaryStatsFetcher.fetch(
            self.clickhouse_store, patient_id, start_date_str, end_date_str
        )
        glucose_range_stats = GlucoseRangeStatsFetcher.fetch(
            self.clickhouse_store, patient_id, start_date_str, end_date_str
        )
        hyper_stats = HyperStatsFetcher().fetch(
            self.clickhouse_store, patient_id, start_date_str, end_date_str
        )
        hypo_stats = HypoStatsFetcher().fetch(
            self.clickhouse_store, patient_id, start_date_str, end_date_str
        )
        time_period_stats = GlucoseTimePeriodStatsFetcher.fetch(
            self.clickhouse_store, patient_id, start_date_str, end_date_str
        )

        fitness_report = self.fitness_stats_processor.generate_report(
            patient_id, start_date, end_date, include_overall=True
        )["overall"]

        glucose_readings = None
        if report_type == "daily":
            glucose_readings = self.fetch_glucose_readings_by_date(
                patient_id, start_date_str, end_date_str
            )

        meal_report_id = None
        if report_type == "daily":
            unique_key = f"{patient_id}_{report_type}_{start_date.date()}"
            meal_report_id = hashlib.sha256(unique_key.encode()).hexdigest()

        return GlucoseLevelStats(
            start_date=start_date,
            end_date=end_date,
            glucose_readings=glucose_readings,
            glucose_summary_stats=glucose_summary_stats,
            glucose_range_stats=glucose_range_stats,
            hyper_stats=hyper_stats,
            hypo_stats=hypo_stats,
            time_period_stats=time_period_stats,
            fitness_report=fitness_report,
            meal_report_id=meal_report_id,
        )

    async def _process_multiple_periods(
        self,
        patient_id: str,
        periods: List[Dict[str, datetime]],
        report_type: ReportTypeLiteral,
    ) -> List[GlucoseLevelStats]:
        stats = []
        for period in periods:
            stats.append(
                await self._process_period(
                    patient_id,
                    period["start_date"],
                    period["end_date"],
                    report_type,
                )
            )
        return stats
