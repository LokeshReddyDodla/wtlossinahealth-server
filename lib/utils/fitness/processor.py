import calendar
import math
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from lib.schemas.fitness_stats import (FitnessActivityDistribution,
                                       FitnessHourlyStats,
                                       FitnessInactivePeriod,
                                       FitnessPeakActivityTime, FitnessStats)
from lib.utils.date.periods import DayWisePeriod, WeekWisePeriod
from lib.utils.fitness.queries import (
    generate_activity_distribution_query,
    generate_average_active_session_duration_query,
    generate_hourly_stats_query, generate_inactive_periods_query,
    generate_peak_activity_time_query, generate_summary_stats_query)


class FitnessStatsProcessor:
    def __init__(self, clickhouse_store):
        self.clickhouse_store = clickhouse_store

    def generate_report(
        self,
        patient_id: str,
        from_date: datetime,
        to_date: datetime,
        include_overall: bool = False,
        include_day_wise: bool = False,
        include_week_wise: bool = False,
    ) -> Dict[str, Any]:
        stats = {}

        # Overall Stats
        if include_overall:
            stats["overall"] = self._process_period(
                patient_id,
                from_date,
                to_date,
            )

        # Day-wise Stats
        if include_day_wise:
            day_periods = DayWisePeriod(from_date, to_date).periods
            stats["day_wise"] = self._process_multiple_periods(
                patient_id,
                day_periods,
            )

        # Week-wise Stats
        if include_week_wise:
            week_periods = WeekWisePeriod(from_date, to_date).periods
            stats["week_wise"] = self._process_multiple_periods(
                patient_id,
                week_periods,
            )

        return stats

    def _process_period(
        self,
        patient_id: str,
        from_date: datetime,
        to_date: datetime,
    ) -> FitnessStats:

        from_date_str = from_date.strftime("%Y-%m-%dT%H:%M:%S")
        to_date_str = to_date.strftime("%Y-%m-%dT%H:%M:%S")

        summary_query = generate_summary_stats_query(
            patient_id, from_date_str, to_date_str
        )
        summary_stats = self.clickhouse_store.client.execute(summary_query)

        # Calculate average active session duration
        avg_active_session_query = (
            generate_average_active_session_duration_query(
                patient_id, from_date_str, to_date_str
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
            patient_id, from_date_str, to_date_str
        )
        activity_distribution = self._fetch_activity_distribution(
            activity_distribution_query
        )

        peak_activity_time_query = generate_peak_activity_time_query(
            patient_id, from_date_str, to_date_str
        )
        peak_activity_time = self._fetch_peak_activity_time(
            peak_activity_time_query
        )

        inactive_periods_query = generate_inactive_periods_query(
            patient_id, from_date_str, to_date_str
        )
        inactive_periods = self._fetch_inactive_periods(inactive_periods_query)

        hourly_stats = self._fetch_hourly_stats(
            patient_id, from_date_str, to_date_str
        )

        return FitnessStats(
            from_date=from_date,
            to_date=to_date,
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
    ) -> List[FitnessStats]:
        stats = []
        for period in periods:
            stats.append(
                self._process_period(
                    patient_id,
                    period["from_date"],
                    period["to_date"],
                )
            )
        return stats

    def _fetch_hourly_stats(
        self, patient_id: str, from_date_str: str, to_date_str: str
    ) -> List[FitnessHourlyStats]:
        query = generate_hourly_stats_query(
            patient_id, from_date_str, to_date_str
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
