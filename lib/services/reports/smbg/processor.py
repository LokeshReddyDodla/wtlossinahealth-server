"""SMBG statistics processor for generating patient reports."""

import calendar
from datetime import datetime
from typing import Any, Dict, List

from lib.schemas.smbg_stats import (
    DateRange,
    GlucoseStatistics,
    MealWindowBreakdown,
    MealWindowGlucoseStats,
    MonthlyGlucoseStats,
    MonthlyPeriod,
    MonthlySummary,
    MonthlyTrends,
    OverallScore,
    ReportMetadata,
    ReportSummary,
    SMBGReadingValue,
    SMBGReport,
    WeeklyTrend,
    WeeklyTrendGlucose,
    WeeklyTrendPeriod,
    MealRangeStats,
)
from lib.utils.date.periods import WeekWisePeriod
from lib.utils.postgres_session_decorator import with_postgres_session

from .constants import (
    PRE_MEAL_TYPES,
    POST_MEAL_TYPES,
)
from .meal_window_bucketer import MealWindowBucketer
from .queries import SMBGQueries
from .statistics import SMBGStatistics


class SMBGStatsProcessor:
    """Processor for generating SMBG statistics and reports."""

    def __init__(
        self,
        postgres_store,
        meal_stats_processor,
    ):
        self.postgres_store = postgres_store
        self.meal_stats_processor = meal_stats_processor

    @with_postgres_session
    async def get_stats(
        self,
        patient_id: str,
        start_date: datetime,
        end_date: datetime,
        *,
        postgres_session,
    ) -> SMBGReport:
        """Get comprehensive SMBG statistics for a date range."""
        start_date = datetime.combine(start_date.date(), datetime.min.time())
        end_date = datetime.combine(end_date.date(), datetime.max.time())

        smbg_records = await SMBGQueries.fetch_readings_in_range(
            postgres_session, patient_id, start_date, end_date
        )

        if not smbg_records:
            days_covered = (end_date.date() - start_date.date()).days + 1
            return SMBGReport(
                metadata=ReportMetadata(
                    date_range=DateRange(
                        start=start_date.isoformat(),
                        end=end_date.isoformat(),
                    ),
                    total_readings=0,
                    days_covered=days_covered,
                ),
                summary=ReportSummary(
                    glucose=GlucoseStatistics(
                        count=0,
                        median=None,
                        highest=None,
                        lowest=None,
                        out_of_range_count=0,
                        average_time_of_day=None,
                    ),
                    meal_statistics={},
                ),
                breakdowns=MealWindowBreakdown(by_meal_window={}),
                trends=MonthlyTrends(monthly=[]),
                readings_by_date={},
            )

        buckets = MealWindowBucketer.bucketize_by_meal(smbg_records)
        meal_windows_stats = await self._calculate_meal_window_stats(buckets)
        overall_stats = await self._calculate_overall_stats(
            smbg_records, patient_id, start_date, end_date, postgres_session
        )
        monthly_summaries = await self._calculate_month_summary(
            patient_id, start_date, end_date, postgres_session
        )
        readings_by_date = self._group_readings_by_date(smbg_records)
        days_covered = (end_date.date() - start_date.date()).days + 1

        return SMBGReport(
            metadata=ReportMetadata(
                date_range=DateRange(
                    start=start_date.isoformat(),
                    end=end_date.isoformat(),
                ),
                total_readings=len(smbg_records),
                days_covered=days_covered,
            ),
            summary=ReportSummary(
                glucose=GlucoseStatistics(
                    count=overall_stats.get("count", 0),
                    median=overall_stats.get("median"),
                    highest=overall_stats.get("highest"),
                    lowest=overall_stats.get("lowest"),
                    out_of_range_count=overall_stats.get("out_of_range", 0),
                    average_time_of_day=overall_stats.get("average_time"),
                ),
                meal_statistics=overall_stats.get("meal_statistics", {}),
            ),
            breakdowns=MealWindowBreakdown(by_meal_window=meal_windows_stats),
            trends=MonthlyTrends(monthly=monthly_summaries),
            readings_by_date=readings_by_date,
        )

    def _group_readings_by_date(
        self, smbg_records: list
    ) -> Dict[str, List[SMBGReadingValue]]:
        """Group SMBG readings by date."""
        grouped: Dict[str, List[SMBGReadingValue]] = {}

        for record in sorted(smbg_records, key=lambda r: r.reading_time):
            reading_date = record.reading_time.date().isoformat()
            grouped.setdefault(reading_date, []).append(
                SMBGReadingValue(
                    reading_time=record.reading_time.isoformat(),
                    glucose_level=record.glucose_level,
                    type=record.type,
                    source_name=record.source_name,
                    source_platform=record.source_platform,
                    notes=record.notes,
                )
            )

        return grouped

    async def _calculate_meal_window_stats(
        self,
        buckets: Dict[str, list],
    ) -> Dict[str, MealWindowGlucoseStats]:
        """Calculate statistics for each meal window."""
        meal_windows_stats = {}

        for bucket_name, readings in buckets.items():
            if not readings:
                continue

            stats = SMBGStatistics.calculate_window_stats(readings)

            meal_windows_stats[bucket_name] = MealWindowGlucoseStats(
                glucose=GlucoseStatistics(
                    count=stats.get("count", 0),
                    median=stats.get("median"),
                    highest=stats.get("highest"),
                    lowest=stats.get("lowest"),
                    out_of_range_count=stats.get("out_of_range", 0),
                    average_time_of_day=stats.get("average_time"),
                ),
            )

        return meal_windows_stats

    async def _calculate_overall_stats(
        self,
        smbg_records: list,
        patient_id: str,
        start_date: datetime,
        end_date: datetime,
        postgres_session,
    ) -> Dict[str, Any]:
        """Calculate overall statistics for all readings."""
        all_times = [r.reading_time for r in smbg_records]

        stats = SMBGStatistics.calculate_basic_stats(smbg_records)
        stats["average_time"] = SMBGStatistics.average_time(all_times)
        meal_statistics_report = await (
            self.meal_stats_processor.get_meal_statistics_in_range(
                patient_id, start_date, end_date
            )
        )
        stats["meal_statistics"] = meal_statistics_report.model_dump()

        return stats

    async def _calculate_month_summary(
        self,
        patient_id: str,
        start_date: datetime,
        end_date: datetime,
        postgres_session,
    ) -> List[MonthlySummary]:
        """Calculate monthly summary statistics for all months in the date range."""
        monthly_summaries = []
        current_date = datetime(start_date.year, start_date.month, 1)
        end_month = datetime(end_date.year, end_date.month, 1)

        while current_date <= end_month:
            month_start = datetime(current_date.year, current_date.month, 1)
            last_day = calendar.monthrange(current_date.year, current_date.month)[1]
            month_end = datetime(
                current_date.year, current_date.month, last_day, 23, 59, 59
            )

            if month_start < start_date:
                month_start = start_date
            if month_end > end_date:
                month_end = end_date

            month_records = await SMBGQueries.fetch_readings_in_range(
                postgres_session, patient_id, month_start, month_end
            )
            meal_summary = await self.meal_stats_processor.get_meal_month_summary(
                patient_id=patient_id,
                start_date=month_start,
                end_date=month_end,
            )

            if not month_records:
                monthly_summaries.append(
                    MonthlySummary(
                        period=MonthlyPeriod(
                            start=month_start.isoformat(),
                            end=month_end.isoformat(),
                            year=current_date.year,
                            month=current_date.month,
                            month_name=calendar.month_name[current_date.month],
                        ),
                        glucose=MonthlyGlucoseStats(
                            total_readings=0,
                            pre_meal=MealRangeStats(
                                count=0,
                                within_range_count=0,
                                within_range_percentage=0.0,
                            ),
                            post_meal=MealRangeStats(
                                count=0,
                                within_range_count=0,
                                within_range_percentage=0.0,
                            ),
                            overall_score=OverallScore(
                                pre_meal=0.0,
                                post_meal=0.0,
                                overall=0.0,
                            ),
                            weekly_trends={},
                        ),
                        meal=meal_summary,
                    )
                )
            else:
                pre_meal = SMBGQueries.filter_by_type(month_records, PRE_MEAL_TYPES)
                post_meal = SMBGQueries.filter_by_type(month_records, POST_MEAL_TYPES)
                summary_stats = SMBGStatistics.calculate_summary_stats(pre_meal, post_meal)
                weekly_trends = self._calculate_weekly_trends(
                    month_records, month_start, month_end
                )

                monthly_summaries.append(
                    MonthlySummary(
                        period=MonthlyPeriod(
                            start=month_start.isoformat(),
                            end=month_end.isoformat(),
                            year=current_date.year,
                            month=current_date.month,
                            month_name=calendar.month_name[current_date.month],
                        ),
                        glucose=MonthlyGlucoseStats(
                            total_readings=len(month_records),
                            pre_meal=MealRangeStats(
                                count=summary_stats.get("pre_meal", {}).get("count", 0),
                                within_range_count=summary_stats.get("pre_meal", {}).get(
                                    "within_range", 0
                                ),
                                within_range_percentage=summary_stats.get("pre_meal", {}).get(
                                    "within_range_pct", 0.0
                                ),
                            ),
                            post_meal=MealRangeStats(
                                count=summary_stats.get("post_meal", {}).get("count", 0),
                                within_range_count=summary_stats.get("post_meal", {}).get(
                                    "within_range", 0
                                ),
                                within_range_percentage=summary_stats.get("post_meal", {}).get(
                                    "within_range_pct", 0.0
                                ),
                            ),
                            overall_score=OverallScore(
                                pre_meal=summary_stats.get("score", {}).get("pre_meal", 0.0),
                                post_meal=summary_stats.get("score", {}).get("post_meal", 0.0),
                                overall=summary_stats.get("score", {}).get("overall", 0.0),
                            ),
                            weekly_trends=weekly_trends,
                        ),
                        meal=meal_summary,
                    )
                )

            if current_date.month == 12:
                current_date = datetime(current_date.year + 1, 1, 1)
            else:
                current_date = datetime(current_date.year, current_date.month + 1, 1)

        return monthly_summaries

    def _calculate_weekly_trends(
        self,
        records: list,
        start_date: datetime,
        end_date: datetime,
    ) -> Dict[str, WeeklyTrend]:
        """Calculate weekly trends for the month."""
        weeks = WeekWisePeriod(start_date, end_date).periods
        trend = {}

        for week in weeks:
            week_start = week["start_date"]
            week_end = week["end_date"]
            week_no = week["week_no"]
            iso_week_no = week["iso_week_no"]

            week_records = SMBGQueries.filter_by_date_range(
                records, week_start, week_end
            )
            pre_week = [
                r.glucose_level
                for r in SMBGQueries.filter_by_type(week_records, PRE_MEAL_TYPES)
            ]
            post_week = [
                r.glucose_level
                for r in SMBGQueries.filter_by_type(week_records, POST_MEAL_TYPES)
            ]

            trend[f"week_{week_no}"] = WeeklyTrend(
                period=WeeklyTrendPeriod(
                    start=week_start.isoformat(),
                    end=week_end.isoformat(),
                    week_number=week_no,
                    iso_week_number=iso_week_no,
                ),
                glucose_medians=WeeklyTrendGlucose(
                    pre_meal=SMBGStatistics.calculate_median(pre_week),
                    post_meal=SMBGStatistics.calculate_median(post_week),
                ),
            )

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
        """Get monthly summary statistics."""
        records = await SMBGQueries.fetch_readings_in_range(
            postgres_session, patient_id, start_date, end_date
        )

        if not records:
            return {}

        pre_meal = SMBGQueries.filter_by_type(records, PRE_MEAL_TYPES)
        post_meal = SMBGQueries.filter_by_type(records, POST_MEAL_TYPES)
        summary_stats = SMBGStatistics.calculate_summary_stats(pre_meal, post_meal)
        trend = self._calculate_weekly_trends(records, start_date, end_date)

        return {
            "total_smbg": len(records),
            **summary_stats,
            "trend": trend,
        }
