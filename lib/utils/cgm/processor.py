import hashlib
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from lib.schemas.cgm_stats import CGMStats, CGMReading
from lib.services.meal_report_service import MealReportService
from lib.utils.date.periods import DayWisePeriod, WeekWisePeriod
from lib.utils.fitness.processor import (
    FitnessReportType,
    FitnessStatsProcessor,
)
from lib.utils.cgm.hyper_stats_fetcher import HyperStatsFetcher
from lib.utils.cgm.hypo_stats_fetcher import HypoStatsFetcher
from lib.utils.cgm.queries import (
    generate_hourly_avg_cgm_query,
    generate_cgm_readings_around_meal_query,
    generate_cgm_readings_in_range_query,
)
from lib.utils.cgm.range import CGMRangeStatsFetcher
from lib.utils.cgm.summary import CGMSummaryStatsFetcher
from lib.utils.cgm.time_period import GlucoseTimePeriodStatsFetcher


class CGMReportType:
    DAILY = "daily"
    WEEKLY = "weekly"
    CUSTOM = "custom"


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
            CGMReading(device_timestamp=row[0], glucose=row[1]) for row in data
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
            CGMReading(device_timestamp=row[1], glucose=row[2]) for row in data
        ]
        return grouped

    def get_cgm_readings_around_meal(
        self,
        patient_id: str,
        meal_time: datetime,
        before_minutes=15,
        after_minutes=90,
    ):
        """Fetch cgm readings around the meal time."""
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
    ) -> List[CGMStats]:
        start_date = start_date.replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        end_date = end_date.replace(
            hour=23, minute=59, second=59, microsecond=999999
        )

        reports: List[CGMStats] = []

        # Overall
        reports.append(
            await self._process_period(
                patient_id, start_date, end_date, CGMReportType.CUSTOM
            )
        )

        # Daily
        day_periods = DayWisePeriod(start_date, end_date).periods
        reports.extend(
            await self._process_multiple_periods(
                patient_id, day_periods, CGMReportType.DAILY
            )
        )

        # Weekly
        week_periods = WeekWisePeriod(start_date, end_date).periods
        reports.extend(
            await self._process_multiple_periods(
                patient_id, week_periods, CGMReportType.WEEKLY
            )
        )

        return reports

    async def _process_period(
        self,
        patient_id: str,
        start_date: datetime,
        end_date: datetime,
        report_type: str,
    ) -> CGMStats:
        start_date_str = start_date.strftime("%Y-%m-%dT%H:%M:%S")
        end_date_str = end_date.strftime("%Y-%m-%dT%H:%M:%S")

        cgm_summary_stats = CGMSummaryStatsFetcher.fetch(
            self.clickhouse_store, patient_id, start_date_str, end_date_str
        )
        cgm_range_stats = CGMRangeStatsFetcher.fetch(
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

        fitness_report = self.fitness_stats_processor.generate_custom_report(
            patient_id,
            start_date,
            end_date,
            report_type=report_type,
        )

        cgm_readings: Optional[List[CGMReading]] = None
        meal_report_id: Optional[str] = None

        if report_type == CGMReportType.DAILY:
            cgm_readings = self.get_cgm_readings_in_range(
                patient_id, start_date_str, end_date_str
            )
            meal_report_id = hashlib.sha256(
                f"{patient_id}_{report_type}_{start_date.date()}".encode()
            ).hexdigest()

        return CGMStats(
            start_date=start_date,
            end_date=end_date,
            report_type=report_type,
            cgm_readings=cgm_readings,
            cgm_summary_stats=cgm_summary_stats,
            cgm_range_stats=cgm_range_stats,
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
        report_type: str,
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
