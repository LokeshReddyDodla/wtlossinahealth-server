import hashlib
from datetime import datetime
from typing import Any, Dict, List, Literal

from lib.schemas.cgm_stats import CGMStats, CGMReading
from lib.services.meal_report_service import MealReportService
from lib.utils.date.periods import DayWisePeriod, WeekWisePeriod
from lib.utils.fitness.processor import FitnessStatsProcessor
from lib.utils.cgm.hyper_stats_fetcher import HyperStatsFetcher
from lib.utils.cgm.hypo_stats_fetcher import HypoStatsFetcher
from lib.utils.cgm.queries import (
    generate_hourly_avg_cgm_query,
    generate_cgm_readings_around_meal_query,
    generate_cgm_readings_in_range_query,
)
from lib.utils.cgm.range import CGMRangeStatsFetcher
from lib.utils.cgm.summary import GlucoseSummaryStatsFetcher
from lib.utils.cgm.time_period import GlucoseTimePeriodStatsFetcher

ReportTypeLiteral = Literal["daily", "weekly", "custom", "other"]


class CGMStatsProcessor:
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

    def get_cgm_readings_in_range(
        self,
        patient_id: str,
        start_date_str: str,
        end_date_str: str,
    ) -> List[CGMReading]:
        query = generate_cgm_readings_in_range_query(
            patient_id, start_date_str, end_date_str
        )
        data = self.clickhouse_store.client.execute(query)
        if not data:
            return []

        readings = [
            CGMReading(Device_Timestamp=row[0], Glucose_Level=row[1])
            for row in data
        ]
        return readings

    def get_hourly_avg_cgm_readings(
        self, patient_id: str, start_date_str: str, end_date_str: str
    ) -> List[CGMReading]:
        query = generate_hourly_avg_cgm_query(
            patient_id, start_date_str, end_date_str
        )
        data = self.clickhouse_store.client.execute(query)
        if not data:
            return []

        grouped = [
            CGMReading(Device_Timestamp=row[1], Glucose_Level=row[2])
            for row in data
        ]
        return grouped

    def get_cgm_readings_around_meal(
        self,
        patient_id: str,
        meal_time: datetime,
        before_minutes=15,
        after_minutes=90,
    ):
        """Fetch glucose readings around the meal time."""
        query = generate_cgm_readings_around_meal_query(
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
    ) -> CGMStats:
        start_date_str = start_date.strftime("%Y-%m-%dT%H:%M:%S")
        end_date_str = end_date.strftime("%Y-%m-%dT%H:%M:%S")

        glucose_summary_stats = GlucoseSummaryStatsFetcher.fetch(
            self.clickhouse_store, patient_id, start_date_str, end_date_str
        )
        glucose_range_stats = CGMRangeStatsFetcher.fetch(
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
        )[
            "overall"
        ]  # TODO store it in fitness_report (report_type=custom)

        glucose_readings = None
        if report_type == "daily":
            glucose_readings = self.get_cgm_readings_in_range(
                patient_id, start_date_str, end_date_str
            )

        meal_report_id = None
        if report_type == "daily":
            unique_key = f"{patient_id}_{report_type}_{start_date.date()}"
            meal_report_id = hashlib.sha256(unique_key.encode()).hexdigest()

        return CGMStats(
            start_date=start_date,
            end_date=end_date,
            report_type=report_type,
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
    ) -> List[CGMStats]:
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
