"""SMBG statistics processor for generating patient reports."""

import calendar
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from lib.core.postgres_store import PostgresStore
from lib.utils.date.periods import WeekWisePeriod
from lib.utils.postgres_session_decorator import with_postgres_session

from .constants import (
    PRE_MEAL_TYPES,
    POST_MEAL_TYPES,
    PREVIOUS_WEEK_OFFSET_DAYS,
)
from .meal_window_bucketer import MealWindowBucketer
from .queries import SMBGQueries
from .statistics import SMBGStatistics


class SMBGStatsProcessor:
    """Processor for generating SMBG statistics and reports."""

    def __init__(
        self,
        postgres_store: PostgresStore,
        patient_profile_service,
        patient_plan_service,
        meal_stats_processor,
    ):
        """
        Initialize SMBG stats processor.

        Args:
            postgres_store: PostgreSQL store instance
            patient_profile_service: Patient profile service
            patient_plan_service: Patient plan service
            meal_stats_processor: Meal statistics processor
        """
        self.postgres_store = postgres_store
        self.patient_profile_service = patient_profile_service
        self.patient_plan_service = patient_plan_service
        self.meal_stats_processor = meal_stats_processor

    @with_postgres_session
    async def get_stats(
        self,
        patient_id: str,
        start_date: datetime,
        end_date: datetime,
        *,
        postgres_session,
    ) -> Dict[str, Any]:
        """
        Get comprehensive SMBG statistics for a date range.

        Args:
            patient_id: Patient identifier
            start_date: Start datetime
            end_date: End datetime
            postgres_session: Database session

        Returns:
            Dictionary containing SMBG statistics
        """
        # Normalize dates to full day range
        start_date = datetime.combine(start_date.date(), datetime.min.time())
        end_date = datetime.combine(end_date.date(), datetime.max.time())

        # Fetch SMBG readings in a single query
        smbg_records = await SMBGQueries.fetch_readings_in_range(
            postgres_session, patient_id, start_date, end_date
        )

        if not smbg_records:
            return {}

        # Classify readings into meal windows
        buckets = MealWindowBucketer.bucketize_by_meal(smbg_records)

        # Build meal window statistics
        meal_windows_stats = self._calculate_meal_window_stats(
            buckets, patient_id, start_date, end_date, postgres_session
        )

        # Build overall statistics
        overall_stats = self._calculate_overall_stats(
            smbg_records, patient_id, start_date, end_date, postgres_session
        )

        # Build month summary
        month_summary = await self._calculate_month_summary(
            patient_id, start_date, end_date, postgres_session
        )

        return {
            "start_date": start_date,
            "end_date": end_date,
            "meal_windows": meal_windows_stats,
            "overall": overall_stats,
            "month_summary": month_summary,
        }

    def _calculate_meal_window_stats(
        self,
        buckets: Dict[str, list],
        patient_id: str,
        start_date: datetime,
        end_date: datetime,
        postgres_session,
    ) -> Dict[str, Any]:
        """
        Calculate statistics for each meal window.

        Args:
            buckets: Dictionary of bucketed readings
            patient_id: Patient identifier
            start_date: Start datetime
            end_date: End datetime
            postgres_session: Database session

        Returns:
            Dictionary of meal window statistics
        """
        meal_windows_stats = {}

        for bucket_name, readings in buckets.items():
            if not readings:
                continue

            stats = SMBGStatistics.calculate_window_stats(readings)
            stats["median_prev_week"] = self._get_previous_week_median(
                patient_id, start_date, end_date, bucket_name, postgres_session
            )

            meal_windows_stats[bucket_name] = stats

        return meal_windows_stats

    def _calculate_overall_stats(
        self,
        smbg_records: list,
        patient_id: str,
        start_date: datetime,
        end_date: datetime,
        postgres_session,
    ) -> Dict[str, Any]:
        """
        Calculate overall statistics for all readings.

        Args:
            smbg_records: List of SMBG records
            patient_id: Patient identifier
            start_date: Start datetime
            end_date: End datetime
            postgres_session: Database session

        Returns:
            Dictionary of overall statistics
        """
        all_times = [r.reading_time for r in smbg_records]

        stats = SMBGStatistics.calculate_basic_stats(smbg_records)
        stats["average_time"] = SMBGStatistics.average_time(all_times)
        stats["median_prev_week"] = self._get_previous_week_median(
            patient_id, start_date, end_date, None, postgres_session
        )

        # Get meal statistics
        stats["meal_statistics"] = (
            self.meal_stats_processor.get_meal_statistics_in_range(
                patient_id, start_date, end_date
            )
        )

        return stats

    async def _calculate_month_summary(
        self,
        patient_id: str,
        start_date: datetime,
        end_date: datetime,
        postgres_session,
    ) -> Dict[str, Any]:
        """
        Calculate monthly summary statistics.

        Args:
            patient_id: Patient identifier
            start_date: Start datetime
            end_date: End datetime
            postgres_session: Database session

        Returns:
            Dictionary of monthly summary statistics
        """
        # Calculate month boundaries
        month_start = datetime(start_date.year, start_date.month, 1)
        last_day = calendar.monthrange(start_date.year, start_date.month)[1]
        month_end = datetime(
            start_date.year, start_date.month, last_day, 23, 59, 59
        )

        # Fetch all records for the month
        month_records = await SMBGQueries.fetch_readings_in_range(
            postgres_session, patient_id, month_start, month_end
        )

        if not month_records:
            return {
                "start_date": month_start,
                "end_date": month_end,
                "smbg": {},
                "meal": await self.meal_stats_processor.get_meal_month_summary(
                    patient_id=patient_id,
                    start_date=month_start,
                    end_date=month_end,
                ),
            }

        # Split pre vs post meal
        pre_meal = SMBGQueries.filter_by_type(month_records, PRE_MEAL_TYPES)
        post_meal = SMBGQueries.filter_by_type(month_records, POST_MEAL_TYPES)

        # Calculate summary stats
        summary_stats = SMBGStatistics.calculate_summary_stats(pre_meal, post_meal)

        # Calculate weekly trends
        trend = self._calculate_weekly_trends(
            month_records, month_start, month_end
        )

        smbg_summary = {
            "total_smbg": len(month_records),
            **summary_stats,
            "trend": trend,
        }

        return {
            "start_date": month_start,
            "end_date": month_end,
            "smbg": smbg_summary,
            "meal": await self.meal_stats_processor.get_meal_month_summary(
                patient_id=patient_id,
                start_date=month_start,
                end_date=month_end,
            ),
        }

    def _calculate_weekly_trends(
        self,
        records: list,
        start_date: datetime,
        end_date: datetime,
    ) -> Dict[str, Any]:
        """
        Calculate weekly trends for the month.

        Args:
            records: List of SMBG records
            start_date: Month start date
            end_date: Month end date

        Returns:
            Dictionary of weekly trend data
        """
        weeks = WeekWisePeriod(start_date, end_date).periods
        trend = {}
        current = start_date

        for week in weeks:
            week_start = week["start_date"]
            week_end = week["end_date"]
            week_no = week["week_no"]
            iso_week_no = week["iso_week_no"]

            # Filter records for this week
            week_records = SMBGQueries.filter_by_date_range(
                records, current, week_end
            )

            # Split by meal type
            pre_week = [
                r.glucose_level
                for r in SMBGQueries.filter_by_type(week_records, PRE_MEAL_TYPES)
            ]
            post_week = [
                r.glucose_level
                for r in SMBGQueries.filter_by_type(week_records, POST_MEAL_TYPES)
            ]

            trend[f"week_{week_no}"] = {
                "pre_meal_median": SMBGStatistics.calculate_median(pre_week),
                "post_meal_median": SMBGStatistics.calculate_median(post_week),
                "start_date": week_start,
                "end_date": week_end,
                "iso_week_no": iso_week_no,
            }

            current = week_end + timedelta(days=1)

        return trend

    @with_postgres_session
    async def get_monthly_summary(
        self,
        patient_id: str,
        start_date: datetime,
        end_date: datetime,
        *,
        postgres_session,
    ) -> Dict[str, Any]:
        """
        Get monthly summary statistics.

        Args:
            patient_id: Patient identifier
            start_date: Start datetime
            end_date: End datetime
            postgres_session: Database session

        Returns:
            Dictionary of monthly summary statistics
        """
        # Fetch records for the month
        records = await SMBGQueries.fetch_readings_in_range(
            postgres_session, patient_id, start_date, end_date
        )

        if not records:
            return {}

        # Split pre vs post meal
        pre_meal = SMBGQueries.filter_by_type(records, PRE_MEAL_TYPES)
        post_meal = SMBGQueries.filter_by_type(records, POST_MEAL_TYPES)

        # Calculate summary stats
        summary_stats = SMBGStatistics.calculate_summary_stats(pre_meal, post_meal)

        # Calculate weekly trends
        trend = self._calculate_weekly_trends(records, start_date, end_date)

        return {
            "total_smbg": len(records),
            **summary_stats,
            "trend": trend,
        }

    async def _get_previous_week_median(
        self,
        patient_id: str,
        start_date: datetime,
        end_date: datetime,
        bucket_name: Optional[str],
        postgres_session,
    ) -> Optional[float]:
        """
        Get median glucose level from previous week.

        Args:
            patient_id: Patient identifier
            start_date: Current period start date
            end_date: Current period end date
            bucket_name: Optional bucket name to filter by
            postgres_session: Database session

        Returns:
            Median value or None
        """
        # Fetch previous week records
        prev_records = await SMBGQueries.fetch_readings_for_previous_week(
            postgres_session,
            patient_id,
            start_date,
            end_date,
            PREVIOUS_WEEK_OFFSET_DAYS,
        )

        if not prev_records:
            return None

        # Filter by bucket if specified
        if bucket_name:
            buckets = MealWindowBucketer.bucketize_by_meal(prev_records)
            readings = buckets.get(bucket_name, [])
        else:
            readings = prev_records

        if not readings:
            return None

        values = [r.glucose_level for r in readings]
        return SMBGStatistics.calculate_median(values)
