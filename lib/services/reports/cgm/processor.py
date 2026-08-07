import hashlib
from datetime import datetime
from typing import Dict, List, Optional

from lib.schemas.cgm_stats import (
    CGMStats,
    CGMReading,
    CGMTrend,
    DateRange,
    ReportMetadata,
)
from lib.utils.date.periods import DayWisePeriod, WeekWisePeriod
from lib.utils.validation_utils import validate_float

from .hyper_stats import HyperglycemiaStatistics
from .hypo_stats import HypoglycemiaStatistics
from .queries import (
    generate_hourly_avg_query,
    generate_readings_around_meal_query,
    generate_readings_in_range_query,
    generate_sensor_active_query,
    generate_total_readings_count_query,
    generate_trend_prev_window_query,
)
from .range_stats import CGMRangeStatistics
from .statistics import CGMStatistics
from .time_period_stats import TimePeriodStatistics


class CGMReportType:
    DAILY = "daily"
    WEEKLY = "weekly"
    CUSTOM = "custom"


class CGMStatsProcessor:
    def __init__(
        self,
        clickhouse_store,
        meal_service,
        fitness_stats_processor,
        meal_report_service,
    ):
        self.clickhouse_store = clickhouse_store
        self.meal_service = meal_service
        self.fitness_stats_processor = fitness_stats_processor
        self.meal_report_service = meal_report_service

    def get_readings_in_range(
        self,
        patient_id: str,
        start_date_str: str,
        end_date_str: str,
    ) -> List[CGMReading]:
        """Get all CGM readings in a date range."""
        query = generate_readings_in_range_query(
            patient_id, start_date_str, end_date_str
        )
        data = self.clickhouse_store.client.execute(query)
        if not data:
            return []

        return [
            CGMReading(device_timestamp=row[0], glucose_mgdl=row[1])
            for row in data
        ]

    def get_hourly_avg_readings(
        self, patient_id: str, start_date_str: str, end_date_str: str
    ) -> List[CGMReading]:
        """Get hourly average CGM readings."""
        query = generate_hourly_avg_query(
            patient_id, start_date_str, end_date_str
        )
        data = self.clickhouse_store.client.execute(query)
        if not data:
            return []

        return [
            CGMReading(device_timestamp=row[1], glucose_mgdl=row[2])
            for row in data
        ]

    def get_readings_around_meal(
        self,
        patient_id: str,
        meal_time: datetime,
        before_minutes: int = 30,
        after_minutes: int = 90,
    ):
        """Get CGM readings around a meal time."""
        query, params = generate_readings_around_meal_query(
            patient_id,
            meal_time.strftime("%Y-%m-%d %H:%M:%S"),
            before_minutes,
            after_minutes,
        )
        results = self.clickhouse_store.client.execute(query, params)

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

        cgm_summary_stats = CGMStatistics.fetch_summary_stats(
            self.clickhouse_store, patient_id, start_date_str, end_date_str
        )
        cgm_range_stats = CGMRangeStatistics.fetch(
            self.clickhouse_store, patient_id, start_date_str, end_date_str
        )
        cgm_summary_stats.gri = CGMRangeStatistics.compute_gri(cgm_range_stats)

        prev_start = start_date - (end_date - start_date)
        trend_result = self.clickhouse_store.client.execute(
            generate_trend_prev_window_query(
                patient_id,
                prev_start.strftime("%Y-%m-%dT%H:%M:%S"),
                start_date_str,
            )
        )
        trend: Optional[CGMTrend] = None
        if trend_result and trend_result[0][2]:  # previous window has readings
            prev_avg = validate_float(trend_result[0][0])
            prev_tir = validate_float((trend_result[0][1] / trend_result[0][2]) * 100)
            cur_avg = cgm_summary_stats.average_glucose_mgdl
            cur_tir = cgm_range_stats.in_target_70_180_percent
            trend = CGMTrend(
                previous_average_glucose_mgdl=prev_avg,
                previous_time_in_range_percent=prev_tir,
                delta_average_glucose_mgdl=validate_float(cur_avg - prev_avg),
                delta_time_in_range_percent=validate_float(cur_tir - prev_tir),
                delta_gmi=validate_float(0.02392 * (cur_avg - prev_avg)),
            )
        hyper_stats = HyperglycemiaStatistics().fetch(
            self.clickhouse_store, patient_id, start_date_str, end_date_str
        )
        hypo_stats = HypoglycemiaStatistics().fetch(
            self.clickhouse_store, patient_id, start_date_str, end_date_str
        )
        time_period_stats = TimePeriodStatistics.fetch(
            self.clickhouse_store, patient_id, start_date_str, end_date_str
        )

        fitness_report = await self.fitness_stats_processor.generate_custom_report(
            patient_id,
            start_date,
            end_date,
            report_type=report_type,
        )

        cgm_readings: Optional[List[CGMReading]] = None
        meal_report_id: Optional[str] = None

        if report_type == CGMReportType.DAILY:
            cgm_readings = self.get_readings_in_range(
                patient_id, start_date_str, end_date_str
            )
            meal_report_id = hashlib.sha256(
                f"{patient_id}_{report_type}_{start_date.date()}".encode()
            ).hexdigest()

        days_covered = (end_date.date() - start_date.date()).days + 1
        
        total_readings_query = generate_total_readings_count_query(
            patient_id, start_date_str, end_date_str
        )
        total_readings_result = self.clickhouse_store.client.execute(total_readings_query)
        total_readings = total_readings_result[0][0] if total_readings_result else 0

        # Sensor-active %: scored against the sensor's own cadence (median gap
        # between readings), so 5-min and 15-min devices are both correct.
        median_gap_result = self.clickhouse_store.client.execute(
            generate_sensor_active_query(patient_id, start_date_str, end_date_str)
        )
        median_gap_s = (
            median_gap_result[0][0]
            if median_gap_result and median_gap_result[0][0]
            else 0
        )
        window_seconds = (end_date - start_date).total_seconds()
        sensor_active_percent = (
            round(min(100.0, total_readings * median_gap_s / window_seconds * 100), 1)
            if median_gap_s and window_seconds
            else 0.0
        )

        return CGMStats(
            metadata=ReportMetadata(
                date_range=DateRange(
                    start=start_date.isoformat(),
                    end=end_date.isoformat(),
                ),
                total_readings=total_readings,
                days_covered=days_covered,
                report_type=report_type,
                sensor_active_percent=sensor_active_percent,
            ),
            cgm_readings=cgm_readings,
            cgm_summary_stats=cgm_summary_stats,
            cgm_range_stats=cgm_range_stats,
            hyper_stats=hyper_stats,
            hypo_stats=hypo_stats,
            time_period_stats=time_period_stats,
            trend=trend,
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
