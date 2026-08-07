import logging
import math
from datetime import date, datetime
from typing import Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from lib.models.patient_workout import PatientWorkout
from lib.schemas.fitness_stats import (
    ActivityDistribution,
    DateRange,
    FitnessStats,
    FitnessTrend,
    HourlyStats,
    InactivePeriod,
    PeakActivityTime,
    ReportMetadata,
    WorkoutSummary,
)
from lib.utils.date.periods import DayWisePeriod, WeekWisePeriod

from .queries import (
    generate_activity_distribution_query,
    generate_average_active_session_duration_query,
    generate_days_with_data_query,
    generate_hourly_stats_query,
    generate_inactive_periods_query,
    generate_peak_activity_time_query,
    generate_summary_stats_query,
    generate_trend_prev_window_query,
    generate_workouts_query,
)


class FitnessReportType:
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    CUSTOM = "custom"


class FitnessStatsProcessor:
    def __init__(self, clickhouse_store, postgres_store):
        self.clickhouse_store = clickhouse_store
        self.postgres_store = postgres_store

    async def generate_custom_report(
        self,
        patient_id: str,
        start_date: datetime,
        end_date: datetime,
        report_type: str,
    ) -> Optional[FitnessStats]:
        try:
            manual = await self._fetch_manual_workouts(
                patient_id, start_date.date(), end_date.date()
            )
            return self._process_period(
                patient_id, start_date, end_date, report_type, manual
            )
        except Exception as e:
            logging.error(
                f"Failed to generate {report_type} report for {patient_id} from {start_date} to {end_date}: {e}"
            )
        return None

    async def generate_report(
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
        # Device-synced samples come from ClickHouse, manually-logged workouts
        # from Postgres — fetch the latter once and fold into every covering report.
        manual = await self._fetch_manual_workouts(
            patient_id, start_date.date(), end_date.date()
        )
        reports: List[FitnessStats] = []

        if FitnessReportType.MONTHLY in report_types:
            reports.append(
                self._process_period(
                    patient_id, start_date, end_date, FitnessReportType.MONTHLY, manual
                )
            )

        if FitnessReportType.WEEKLY in report_types:
            week_periods = WeekWisePeriod(start_date, end_date).periods
            reports.extend(
                self._process_multiple_periods(
                    patient_id, week_periods, FitnessReportType.WEEKLY, manual
                )
            )

        if FitnessReportType.DAILY in report_types:
            day_periods = DayWisePeriod(start_date, end_date).periods
            reports.extend(
                self._process_multiple_periods(
                    patient_id, day_periods, FitnessReportType.DAILY, manual
                )
            )

        return reports

    def _process_period(
        self,
        patient_id: str,
        start_date: datetime,
        end_date: datetime,
        report_type: str,
        manual_workouts: Optional[List[PatientWorkout]] = None,
    ) -> FitnessStats:
        start_date_str = start_date.strftime("%Y-%m-%dT%H:%M:%S")
        end_date_str = end_date.strftime("%Y-%m-%dT%H:%M:%S")

        summary_query = generate_summary_stats_query(
            patient_id, start_date_str, end_date_str
        )
        summary_stats = self.clickhouse_store.client.execute(summary_query)

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

        workouts = self._fetch_workouts(patient_id, start_date_str, end_date_str)
        manual = self._manual_summaries(
            manual_workouts, start_date.date(), end_date.date()
        )
        if manual:
            workouts = (workouts or []) + manual

        days_covered = (end_date.date() - start_date.date()).days + 1

        days_with_data_result = self.clickhouse_store.client.execute(
            generate_days_with_data_query(patient_id, start_date_str, end_date_str)
        )
        days_with_data = days_with_data_result[0][0] if days_with_data_result else 0

        row = summary_stats[0] if summary_stats else (0, 0.0, 0.0, 0.0, 0, 0.0)

        prev_start = start_date - (end_date - start_date)
        trend_result = self.clickhouse_store.client.execute(
            generate_trend_prev_window_query(
                patient_id,
                prev_start.strftime("%Y-%m-%dT%H:%M:%S"),
                start_date_str,
            )
        )
        trend: Optional[FitnessTrend] = None
        if trend_result and trend_result[0] and (trend_result[0][0] or trend_result[0][1]):
            prev_steps = int(trend_result[0][0] or 0)
            prev_energy = float(trend_result[0][1] or 0.0)
            prev_duration = float(trend_result[0][2] or 0.0)
            trend = FitnessTrend(
                previous_steps=prev_steps,
                previous_active_energy=prev_energy,
                previous_active_duration=prev_duration,
                delta_steps=int(row[0]) - prev_steps,
                delta_active_energy=row[1] - prev_energy,
                delta_active_duration=row[2] - prev_duration,
            )

        return FitnessStats(
            metadata=ReportMetadata(
                date_range=DateRange(
                    start=start_date.isoformat(),
                    end=end_date.isoformat(),
                ),
                days_covered=days_covered,
                report_type=report_type,
                days_with_data=days_with_data,
            ),
            steps=row[0],
            active_energy=row[1],
            active_duration=row[2],
            distance=row[3],
            flights_climbed=int(row[4]),
            exercise_time=row[5],
            average_active_session_duration=average_active_session_duration,
            activity_distribution=activity_distribution,
            peak_activity_time=peak_activity_time,
            inactive_periods=inactive_periods,
            hourly_stats=hourly_stats,
            workouts=workouts,
            trend=trend,
        )

    def _process_multiple_periods(
        self,
        patient_id: str,
        periods: List[Dict[str, datetime]],
        report_type: str,
        manual_workouts: Optional[List[PatientWorkout]] = None,
    ) -> List[FitnessStats]:
        stats = []
        for period in periods:
            stats.append(
                self._process_period(
                    patient_id,
                    period["start_date"],
                    period["end_date"],
                    report_type,
                    manual_workouts,
                )
            )
        return stats

    def _fetch_hourly_stats(
        self, patient_id: str, start_date_str: str, end_date_str: str
    ) -> List[HourlyStats]:
        query = generate_hourly_stats_query(
            patient_id, start_date_str, end_date_str
        )
        data = self.clickhouse_store.client.execute(query)
        return [
            HourlyStats(
                hour=row[0],
                steps=row[1],
                active_energy=row[2],
                active_duration=row[3],
                distance=row[4],
                flights_climbed=int(row[5]),
            )
            for row in data
        ]

    def _fetch_activity_distribution(
        self, query: str
    ) -> Optional[Dict[str, ActivityDistribution]]:
        data = self.clickhouse_store.client.execute(query)
        return {
            row[0]: ActivityDistribution(
                time_of_day=row[0],
                steps=row[1],
                active_energy=row[2],
                active_duration=row[3],
                distance=row[4],
                flights_climbed=int(row[5]),
            )
            for row in data
        }

    def _fetch_peak_activity_time(
        self, query: str
    ) -> Optional[PeakActivityTime]:
        data = self.clickhouse_store.client.execute(query)
        if data:
            return PeakActivityTime(
                hour=data[0][0],
                max_steps=data[0][1],
                max_active_energy=data[0][2],
                max_distance=data[0][3],
            )
        return None

    def _fetch_inactive_periods(
        self, query: str
    ) -> Optional[List[InactivePeriod]]:
        data = self.clickhouse_store.client.execute(query)
        return [
            InactivePeriod(
                start_time=str(row[0]),
                end_time=str(row[1]),
                inactive_duration=row[2],
            )
            for row in data
        ]

    def _fetch_workouts(
        self, patient_id: str, start_date_str: str, end_date_str: str
    ) -> Optional[List[WorkoutSummary]]:
        query = generate_workouts_query(patient_id, start_date_str, end_date_str)
        data = self.clickhouse_store.client.execute(query)
        if not data:
            return None
        return [
            WorkoutSummary(
                type=row[0],
                session_count=row[1],
                total_duration=row[2],
                total_energy=row[3],
                source=row[4] if len(row) > 4 and row[4] else "synced",
            )
            for row in data
        ]

    async def _fetch_manual_workouts(
        self, patient_id: str, start_date: date, end_date: date
    ) -> List[PatientWorkout]:
        """Manually-logged workouts (Postgres). Segments carry the real
        type/duration — the top-level columns are legacy — so eager-load them."""
        try:
            async with self.postgres_store.get_session() as session:
                result = await session.execute(
                    select(PatientWorkout)
                    .where(
                        PatientWorkout.patient_id == UUID(patient_id),
                        PatientWorkout.date >= start_date,
                        PatientWorkout.date <= end_date,
                    )
                    .options(selectinload(PatientWorkout.segments))
                )
                return list(result.scalars().all())
        except Exception as e:
            logging.warning(f"Failed to fetch manual workouts for {patient_id}: {e}")
            return []

    def _manual_summaries(
        self,
        workouts: Optional[List[PatientWorkout]],
        start_date: date,
        end_date: date,
    ) -> List[WorkoutSummary]:
        return [
            self._workout_summary(w)
            for w in (workouts or [])
            if start_date <= w.date <= end_date
        ]

    @staticmethod
    def _workout_summary(w: PatientWorkout) -> WorkoutSummary:
        segments = w.segments or []
        total = sum(s.duration_minutes or 0 for s in segments) or (
            w.duration_minutes or 0
        )
        types = sorted({s.type for s in segments if s.type}) or (
            [w.type] if w.type else []
        )
        return WorkoutSummary(
            type=", ".join(types).title() if types else "Workout",
            session_count=1,
            total_duration=float(total),
            total_energy=float(w.calories_burned or 0),
            source=w.source or "app",
            workout_id=str(w.id),
        )
