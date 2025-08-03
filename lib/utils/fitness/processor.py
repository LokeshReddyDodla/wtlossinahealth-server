import calendar
import math
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from lib.schemas.fitness_stats import (
    FitnessActivityDistribution,
    FitnessHourlyStats,
    FitnessInactivePeriod,
    FitnessPeakActivityTime,
    FitnessStats,
)
from lib.utils.date.periods import DayWisePeriod, WeekWisePeriod
from lib.utils.fitness.queries import (
    generate_activity_distribution_query,
    generate_average_active_session_duration_query,
    generate_hourly_stats_query,
    generate_inactive_periods_query,
    generate_peak_activity_time_query,
    generate_summary_stats_query,
)


class FitnessReportType:
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    CUSTOM = "custom"


class FitnessStatsProcessor:
    def __init__(self, clickhouse_store):
        self.clickhouse_store = clickhouse_store

    def generate_custom_report(
        self,
        patient_id: str,
        start_date: datetime,
        end_date: datetime,
        report_type: str,
    ) -> Optional[FitnessStats]:
        try:
            report = self._process_period(
                patient_id, start_date, end_date, report_type
            )

            return report
        except Exception as e:
            print(
                f"❌ Failed to generate {report_type} report for {patient_id} from {start_date} to {end_date}. Error: {e}"
            )
        return None

    def generate_report(
        self,
        patient_id: str,
        start_date: datetime,
        end_date: datetime,
        report_types: List[str] = [
            FitnessReportType.MONTHLY,
            FitnessReportType.DAILY,
            FitnessReportType.WEEKLY,
        ],
    ) -> List[FitnessStats]:
        reports: List[FitnessStats] = []

        if FitnessReportType.MONTHLY in report_types:
            reports.append(
                self._process_period(
                    patient_id, start_date, end_date, FitnessReportType.MONTHLY
                )
            )

        if FitnessReportType.WEEKLY in report_types:
            week_periods = WeekWisePeriod(start_date, end_date).periods
            reports.extend(
                self._process_multiple_periods(
                    patient_id, week_periods, FitnessReportType.WEEKLY
                )
            )

        if FitnessReportType.DAILY in report_types:
            day_periods = DayWisePeriod(start_date, end_date).periods
            reports.extend(
                self._process_multiple_periods(
                    patient_id, day_periods, FitnessReportType.DAILY
                )
            )

        return reports

    def _process_period(
        self,
        patient_id: str,
        start_date: datetime,
        end_date: datetime,
        report_type: str,
    ) -> FitnessStats:

        start_date_str = start_date.strftime("%Y-%m-%dT%H:%M:%S")
        end_date_str = end_date.strftime("%Y-%m-%dT%H:%M:%S")

        summary_query = generate_summary_stats_query(
            patient_id, start_date_str, end_date_str
        )
        summary_stats = self.clickhouse_store.client.execute(summary_query)

        # Calculate average active session duration
        avg_active_session_query = (
            generate_average_active_session_duration_query(
                patient_id, start_date_str, end_date_str
            )
        )
        avg_active_session_result = self.clickhouse_store.client.execute(
            avg_active_session_query
        )
        average_active_session_duration = (
            avg_active_session_result[0][0]
            if avg_active_session_result
            and not math.isnan(avg_active_session_result[0][0])
            else 0
        )

        # Fetch additional metrics for the overall summary
        activity_distribution_query = generate_activity_distribution_query(
            patient_id, start_date_str, end_date_str
        )
        activity_distribution = self._fetch_activity_distribution(
            activity_distribution_query
        )

        peak_activity_time_query = generate_peak_activity_time_query(
            patient_id, start_date_str, end_date_str
        )
        peak_activity_time = self._fetch_peak_activity_time(
            peak_activity_time_query
        )

        inactive_periods_query = generate_inactive_periods_query(
            patient_id, start_date_str, end_date_str
        )
        inactive_periods = self._fetch_inactive_periods(inactive_periods_query)

        hourly_stats = self._fetch_hourly_stats(
            patient_id, start_date_str, end_date_str
        )

        return FitnessStats(
            start_date=start_date,
            end_date=end_date,
            report_type=report_type,
            steps=summary_stats[0][0],
            active_energy=summary_stats[0][1],
            active_duration=summary_stats[0][2],
            average_active_session_duration=average_active_session_duration,
            activity_distribution=activity_distribution,
            peak_activity_time=peak_activity_time,
            inactive_periods=inactive_periods,
            hourly_stats=hourly_stats,
        )

    def _process_multiple_periods(
        self,
        patient_id: str,
        periods: List[Dict[str, datetime]],
        report_type: str,
    ) -> List[FitnessStats]:
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

    def _fetch_hourly_stats(
        self, patient_id: str, start_date_str: str, end_date_str: str
    ) -> List[FitnessHourlyStats]:
        query = generate_hourly_stats_query(
            patient_id, start_date_str, end_date_str
        )
        data = self.clickhouse_store.client.execute(query)
        return [
            FitnessHourlyStats(
                hour=row[0],
                steps=row[1],
                active_energy=row[2],
                active_duration=row[3],
            )
            for row in data
        ]

    def _fetch_activity_distribution(
        self, query: str
    ) -> Optional[Dict[str, FitnessActivityDistribution]]:
        data = self.clickhouse_store.client.execute(query)
        return {
            row[0]: FitnessActivityDistribution(
                time_of_day=row[0],
                steps=row[1],
                active_energy=row[2],
                active_duration=row[3],
            )
            for row in data
        }

    def _fetch_peak_activity_time(
        self, query: str
    ) -> Optional[FitnessPeakActivityTime]:
        data = self.clickhouse_store.client.execute(query)
        if data:
            return FitnessPeakActivityTime(
                hour=data[0][0],
                max_steps=data[0][1],
                max_active_energy=data[0][2],
            )
        return None

    def _fetch_inactive_periods(
        self, query: str
    ) -> Optional[List[FitnessInactivePeriod]]:
        data = self.clickhouse_store.client.execute(query)
        return [
            FitnessInactivePeriod(
                start_time=row[0],
                end_time=row[1],
                inactive_duration=row[2],
            )
            for row in data
        ]
