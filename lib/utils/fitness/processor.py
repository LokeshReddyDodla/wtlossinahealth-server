from datetime import datetime, timedelta
import math
from typing import List, Dict, Optional
from lib.schemas.fitness import (
    FitnessActivityDistribution,
    FitnessInactivePeriod,
    FitnessPeakActivityTime,
    FitnessSummaryStats,
    FitnessDailyStats,
    FitnessWeekOverWeekComparison,
    FitnessWeeklyStats,
    FitnessMonthlyStats,
    FitnessHourlyStats,
)
from lib.utils.fitness.queries import (
    generate_activity_distribution_query,
    generate_average_active_session_duration_query,
    generate_inactive_periods_query,
    generate_peak_activity_time_query,
    generate_summary_stats_query,
    generate_daily_stats_query,
    generate_week_over_week_comparison_query,
    generate_weekly_stats_query,
    generate_monthly_stats_query,
    generate_hourly_stats_query,
)
from pandas import DataFrame


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
        if result:
            total_steps = result[0][0]
            total_active_energy = result[0][1]
            total_active_duration = result[0][2]

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
            inactive_periods = self._fetch_inactive_periods(
                inactive_periods_query
            )

            return FitnessSummaryStats(
                total_steps=total_steps,
                total_active_energy=total_active_energy,
                total_active_duration=total_active_duration,
                average_active_session_duration=average_active_session_duration,
                activity_distribution=activity_distribution,
                peak_activity_time=peak_activity_time,
                inactive_periods=inactive_periods,
            )
        return FitnessSummaryStats(
            total_steps=0,
            total_active_energy=0.0,
            total_active_duration=0.0,
            average_active_session_duration=0.0,
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
            steps = row[1]
            active_energy = row[2]
            active_duration = row[3]

            # Calculate average active session duration
            avg_active_session_query = (
                generate_average_active_session_duration_query(
                    self.patient_id,
                    date.strftime("%Y-%m-%dT00:00:00"),
                    date.strftime("%Y-%m-%dT23:59:59"),
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

            activity_distribution_query = generate_activity_distribution_query(
                self.patient_id,
                date.strftime("%Y-%m-%dT00:00:00"),
                date.strftime("%Y-%m-%dT23:59:59"),
            )
            activity_distribution = self._fetch_activity_distribution(
                activity_distribution_query
            )

            peak_activity_time_query = generate_peak_activity_time_query(
                self.patient_id,
                date.strftime("%Y-%m-%dT00:00:00"),
                date.strftime("%Y-%m-%dT23:59:59"),
            )
            peak_activity_time = self._fetch_peak_activity_time(
                peak_activity_time_query
            )

            inactive_periods_query = generate_inactive_periods_query(
                self.patient_id,
                date.strftime("%Y-%m-%dT00:00:00"),
                date.strftime("%Y-%m-%dT23:59:59"),
            )
            inactive_periods = self._fetch_inactive_periods(
                inactive_periods_query
            )

            daily_stats.append(
                FitnessDailyStats(
                    date=date,
                    steps=steps,
                    active_energy=active_energy,
                    active_duration=active_duration,
                    average_active_session_duration=average_active_session_duration,
                    activity_distribution=activity_distribution,
                    peak_activity_time=peak_activity_time,
                    inactive_periods=inactive_periods,
                )
            )

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
            steps = row[1]
            active_energy = row[2]
            active_duration = row[3]

            # Adjust format to match the input format
            date_format = "%Y-%m-%dT%H:%M:%S"

            # Parse the date using the correct format
            current_week_start_date = datetime.strptime(
                from_date_str, date_format
            )
            previous_week_start_date = current_week_start_date - timedelta(
                weeks=1
            )
            previous_week_start_str = previous_week_start_date.strftime(
                "%Y-%m-%dT%H:%M:%S"
            )

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
            inactive_periods = self._fetch_inactive_periods(
                inactive_periods_query
            )

            week_over_week_query = generate_week_over_week_comparison_query(
                self.patient_id, from_date_str, previous_week_start_str
            )
            week_over_week_comparison = self._fetch_week_over_week_comparison(
                week_over_week_query
            )

            weekly_stats.append(
                FitnessWeeklyStats(
                    week_number=week_number,
                    steps=steps,
                    active_energy=active_energy,
                    active_duration=active_duration,
                    average_active_session_duration=average_active_session_duration,
                    activity_distribution=activity_distribution,
                    peak_activity_time=peak_activity_time,
                    inactive_periods=inactive_periods,
                    week_over_week_comparison=week_over_week_comparison,
                )
            )

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
            steps = row[1]
            active_energy = row[2]
            active_duration = row[3]

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
            inactive_periods = self._fetch_inactive_periods(
                inactive_periods_query
            )

            week_over_week_query = generate_week_over_week_comparison_query(
                self.patient_id, from_date_str, from_date_str
            )
            week_over_week_comparison = self._fetch_week_over_week_comparison(
                week_over_week_query
            )

            monthly_stats.append(
                FitnessMonthlyStats(
                    month=month,
                    steps=steps,
                    active_energy=active_energy,
                    active_duration=active_duration,
                    average_active_session_duration=average_active_session_duration,
                    activity_distribution=activity_distribution,
                    peak_activity_time=peak_activity_time,
                    inactive_periods=inactive_periods,
                    week_over_week_comparison=week_over_week_comparison,
                )
            )

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
                inactive_duration=row[0],
            )
            for row in data
        ]

    def _fetch_week_over_week_comparison(
        self, query: str
    ) -> Optional[FitnessWeekOverWeekComparison]:
        data = self.clickhouse_store.client.execute(query)
        if data:
            return FitnessWeekOverWeekComparison(
                steps_diff=data[0][0],
                active_energy_diff=data[0][1],
                active_duration_diff=data[0][2],
            )
        return None
