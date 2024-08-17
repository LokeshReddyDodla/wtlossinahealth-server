from datetime import datetime, timedelta
import math
from typing import List, Dict, Optional
from lib.schemas.fitness import (
    FitnessActivityDistribution,
    FitnessInactivePeriod,
    FitnessPeakActivityTime,
    FitnessDailyStats,
    FitnessSummaryStats,
    FitnessWeeklyStats,
    FitnessMonthlyStats,
    FitnessHourlyStats,
)
from lib.utils.fitness.queries import (
    generate_activity_distribution_query,
    generate_average_active_session_duration_query,
    generate_inactive_periods_query,
    generate_peak_activity_time_query,
    generate_daily_stats_query,
    generate_summary_stats_query,
    generate_weekly_stats_query,
    generate_monthly_stats_query,
    generate_hourly_stats_query,
)


class FitnessDataProcessor:
    def __init__(self, clickhouse_store, patient_id: str):
        self.clickhouse_store = clickhouse_store
        self.patient_id = patient_id

    def fetch_summary_stats(
        self, from_date_str: str, to_date_str: str
    ) -> FitnessSummaryStats:
        query = generate_summary_stats_query(
            self.patient_id, from_date_str, to_date_str
        )
        result = self.clickhouse_store.client.execute(query)
        return self._construct_fitness_summary_stats(
            result[0],
            from_date_str,
            to_date_str,
            FitnessSummaryStats,
            index_starts=0,
        )

    def fetch_daily_stats(
        self, from_date_str: str, to_date_str: str
    ) -> List[FitnessDailyStats]:
        query = generate_daily_stats_query(
            self.patient_id, from_date_str, to_date_str
        )
        data = self.clickhouse_store.client.execute(query)

        daily_stats = []
        for row in data:
            date = row[0]
            stats_instance = self._construct_fitness_summary_stats(
                result=row,
                from_date_str=date.strftime("%Y-%m-%dT00:00:00"),
                to_date_str=date.strftime("%Y-%m-%dT23:59:59"),
                stats_class=FitnessDailyStats,
                additional_fields={"date": date},
            )
            daily_stats.append(stats_instance)
        return daily_stats

    def fetch_weekly_stats(
        self, from_date_str: str, to_date_str: str
    ) -> List[FitnessWeeklyStats]:
        query = generate_weekly_stats_query(
            self.patient_id, from_date_str, to_date_str
        )
        data = self.clickhouse_store.client.execute(query)

        weekly_stats = []
        for row in data:
            week_number = row[0]
            stats_instance = self._construct_fitness_summary_stats(
                result=row,
                from_date_str=from_date_str,
                to_date_str=to_date_str,
                stats_class=FitnessWeeklyStats,
                additional_fields={"week_number": week_number},
            )
            weekly_stats.append(stats_instance)
        return weekly_stats

    def fetch_monthly_stats(
        self, from_date_str: str, to_date_str: str
    ) -> List[FitnessMonthlyStats]:
        query = generate_monthly_stats_query(
            self.patient_id, from_date_str, to_date_str
        )
        data = self.clickhouse_store.client.execute(query)

        monthly_stats = []
        for row in data:
            month = row[0]
            stats_instance = self._construct_fitness_summary_stats(
                result=row,
                from_date_str=from_date_str,
                to_date_str=to_date_str,
                stats_class=FitnessMonthlyStats,
                additional_fields={"month": month},
            )
            monthly_stats.append(stats_instance)
        return monthly_stats

    def fetch_hourly_stats(
        self, from_date_str: str, to_date_str: str
    ) -> List[FitnessHourlyStats]:
        query = generate_hourly_stats_query(
            self.patient_id, from_date_str, to_date_str
        )
        data = self.clickhouse_store.client.execute(query)
        hourly_stats = [
            FitnessHourlyStats(
                hour=row[0],
                steps=row[1],
                active_energy=row[2],
                active_duration=row[3],
            )
            for row in data
        ]
        return hourly_stats

    def _construct_fitness_summary_stats(
        self,
        result,
        from_date_str: str,
        to_date_str: str,
        stats_class,
        index_starts: int = 1,
        additional_fields: Dict = {},
    ):
        steps = result[index_starts]
        active_energy = result[index_starts + 1]
        active_duration = result[index_starts + 2]

        # Calculate average active session duration
        avg_active_session_query = (
            generate_average_active_session_duration_query(
                self.patient_id, from_date_str, to_date_str
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
            self.patient_id, from_date_str, to_date_str
        )
        activity_distribution = self._fetch_activity_distribution(
            activity_distribution_query
        )

        peak_activity_time_query = generate_peak_activity_time_query(
            self.patient_id, from_date_str, to_date_str
        )
        peak_activity_time = self._fetch_peak_activity_time(
            peak_activity_time_query
        )

        inactive_periods_query = generate_inactive_periods_query(
            self.patient_id, from_date_str, to_date_str
        )
        inactive_periods = self._fetch_inactive_periods(inactive_periods_query)

        return stats_class(
            steps=steps,
            active_energy=active_energy,
            active_duration=active_duration,
            average_active_session_duration=average_active_session_duration,
            activity_distribution=activity_distribution,
            peak_activity_time=peak_activity_time,
            inactive_periods=inactive_periods,
            **additional_fields
        )

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
