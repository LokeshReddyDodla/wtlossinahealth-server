from datetime import datetime
from typing import List

from lib.schemas.sleep_stats import (
    DateRange,
    ReportMetadata,
    SleepDuration,
    SleepQuality,
    SleepStats,
    SleepTiming,
    SleepTypeDistribution,
)
from lib.utils.date.periods import DayWisePeriod, WeekWisePeriod

from .duration import SleepDurationStatistics
from .quality import SleepQualityStatistics
from .timing import SleepTimingStatistics
from .type_distribution import SleepTypeDistributionStatistics
from .queries import generate_total_sessions_query


class SleepReportType:
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    CUSTOM = "custom"


class SleepStatsProcessor:
    def __init__(self, clickhouse_store):
        self.clickhouse_store = clickhouse_store

    def generate_report(
        self,
        patient_id: str,
        start_datetime: datetime,
        end_datetime: datetime,
        report_types: List[str] = [
            SleepReportType.MONTHLY,
            SleepReportType.DAILY,
            SleepReportType.WEEKLY,
        ],
    ) -> List[SleepStats]:
        reports: List[SleepStats] = []

        if SleepReportType.MONTHLY in report_types:
            reports.append(
                self._process_period(
                    patient_id, start_datetime, end_datetime, SleepReportType.MONTHLY,
                )
            )

        if SleepReportType.WEEKLY in report_types:
            week_periods = WeekWisePeriod(start_datetime, end_datetime).periods
            reports.extend(
                self._process_multiple_periods(
                    patient_id, week_periods, SleepReportType.WEEKLY,
                )
            )

        if SleepReportType.DAILY in report_types:
            day_periods = DayWisePeriod(start_datetime, end_datetime).periods
            reports.extend(
                self._process_multiple_periods(
                    patient_id, day_periods, SleepReportType.DAILY,
                )
            )

        return reports

    def _process_period(
        self,
        patient_id: str,
        start_datetime: datetime,
        end_datetime: datetime,
        report_type: str,
    ) -> SleepStats:
        start_str = start_datetime.strftime("%Y-%m-%dT%H:%M:%S")
        end_str = end_datetime.strftime("%Y-%m-%dT%H:%M:%S")
        days_covered = (end_datetime - start_datetime).days + 1

        query = generate_total_sessions_query(patient_id, start_str, end_str)
        result = self.clickhouse_store.client.execute(query)
        total_sessions = result[0][0] if result else 0

        duration_data = SleepDurationStatistics.fetch(
            self.clickhouse_store, patient_id, start_str, end_str, days_covered,
        )
        type_distribution_data = SleepTypeDistributionStatistics.fetch(
            self.clickhouse_store, patient_id, start_str, end_str, days_covered,
        )
        timing_data = SleepTimingStatistics.fetch(
            self.clickhouse_store, patient_id, start_str, end_str,
        )
        quality_data = SleepQualityStatistics.fetch(
            self.clickhouse_store, patient_id, start_str, end_str,
        )

        return SleepStats(
            metadata=ReportMetadata(
                date_range=DateRange(
                    start=start_datetime.isoformat(),
                    end=end_datetime.isoformat(),
                ),
                total_sessions=total_sessions,
                days_covered=days_covered,
                report_type=report_type,
            ),
            duration=SleepDuration(**duration_data),
            type_distribution=SleepTypeDistribution(**type_distribution_data),
            timing=SleepTiming(**timing_data),
            quality=SleepQuality(**quality_data),
        )

    def _process_multiple_periods(
        self,
        patient_id: str,
        periods: List[dict],
        report_type: str,
    ) -> List[SleepStats]:
        stats = []
        for period in periods:
            stats.append(
                self._process_period(
                    patient_id,
                    period["start_date"],
                    period["end_date"],
                    report_type,
                )
            )
        return stats
