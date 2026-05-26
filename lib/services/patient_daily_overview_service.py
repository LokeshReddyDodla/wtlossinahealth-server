import asyncio
from datetime import date, datetime, timedelta
from typing import Optional

from lib.schemas.patient_daily_overview import (
    BloodPressure,
    FitnessMetrics,
    GlucoseMetrics,
    GlucoseRange,
    GlucoseReading,
    HourlySteps,
    MacroNutrients,
    MealDailySummary,
    PatientDailyOverviewResponse,
    PreviousDaySummary,
    SleepMetrics,
    VitalReading,
    VitalsMetrics,
    WorkoutMetrics,
)
from lib.models.patient_workout import PatientWorkout
from uuid import UUID as _UUID
from lib.services.reports.meal.service import MealReportService
from lib.services.reports.cgm.service import CGMReportService
from lib.services.reports.fitness.service import FitnessReportService
from lib.services.reports.sleep.service import SleepReportService
from lib.core.clickhouse_store import ClickHouseStore
from lib.core.postgres_store import PostgresStore
from sqlalchemy import and_, cast, Date, select
from sqlalchemy.ext.asyncio import AsyncSession
from lib.utils.postgres_session_decorator import with_postgres_session


class PatientDailyOverviewService:
    def __init__(
        self,
        postgres_store: PostgresStore,
        clickhouse_store: ClickHouseStore,
        meal_report_service: MealReportService,
        cgm_report_service: CGMReportService,
        fitness_report_service: FitnessReportService,
        sleep_report_service: SleepReportService,
    ):
        self.postgres_store = postgres_store
        self.clickhouse_store = clickhouse_store
        self.meal_report_service = meal_report_service
        self.cgm_report_service = cgm_report_service
        self.fitness_report_service = fitness_report_service
        self.sleep_report_service = sleep_report_service

    @with_postgres_session
    async def get_daily_overview(
        self,
        patient_id: str,
        selected_date: date,
        *,
        postgres_session: AsyncSession,
    ) -> PatientDailyOverviewResponse:

        (
            meals,
            fitness,
            sleep,
            glucose,
            vitals,
            current_weight,
            weight_trend,
            workouts,
            previous,
        ) = await asyncio.gather(
            self._get_meal_data(patient_id, selected_date),
            self._get_fitness_data(patient_id, selected_date),
            self._get_sleep_data(patient_id, selected_date),
            self._get_cgm_data(patient_id, selected_date),
            self._get_vitals_data(patient_id, selected_date),
            self._get_current_weight(patient_id, selected_date, postgres_session),
            self._get_weight_trend(patient_id, selected_date),
            self._get_workout_data(patient_id, selected_date, postgres_session),
            self._get_previous_day_summary(patient_id, selected_date),
        )

        return PatientDailyOverviewResponse(
            date=selected_date,
            patient_id=patient_id,
            has_active_cgm=bool(glucose.readings),
            meals=meals,
            fitness=fitness,
            sleep=sleep,
            glucose=glucose,
            vitals=vitals,
            workouts=workouts,
            current_weight=current_weight,
            weight_trend=weight_trend,
            previous=previous,
        )

    async def _get_workout_data(
        self,
        patient_id: str,
        selected_date: date,
        session: AsyncSession,
    ) -> WorkoutMetrics:
        rows = (
            await session.execute(
                select(PatientWorkout).where(
                    PatientWorkout.patient_id == _UUID(patient_id),
                    PatientWorkout.date == selected_date,
                )
            )
        ).scalars().all()

        if not rows:
            return WorkoutMetrics()

        total_duration = sum(r.duration_minutes or 0 for r in rows)
        total_calories = sum(r.calories_burned or 0.0 for r in rows)
        types = sorted({r.type for r in rows if r.type})

        return WorkoutMetrics(
            session_count=len(rows),
            total_duration_minutes=total_duration,
            total_calories=total_calories,
            types=types,
        )

    async def _get_meal_data(
        self, patient_id: str, selected_date: date
    ) -> MealDailySummary:
        try:
            report = await self.meal_report_service.fetch_daily_report(
                patient_id, selected_date
            )

            if not report:
                return MealDailySummary(daily=MacroNutrients())

            carbs = report.get("carbohydrates") or report.get("carbs", 0)

            return MealDailySummary(
                daily=MacroNutrients(
                    calories=float(report.get("calories", 0)),
                    carbohydrates=float(carbs),
                    proteins=float(report.get("proteins", 0)),
                    fats=float(report.get("fats", 0)),
                    fiber=float(report.get("fiber", 0)),
                ),
                diet_recommendations=report.get("diet_recommendations"),
            )
        except Exception as e:
            print(f"Meal data error: {e}")
            return MealDailySummary(daily=MacroNutrients())

    async def _get_cgm_data(
        self, patient_id: str, selected_date: date
    ) -> GlucoseMetrics:
        try:
            report = await self.cgm_report_service.fetch_daily_report(
                patient_id, selected_date
            )

            if not report:
                return GlucoseMetrics()

            summary = report.get("cgm_summary_stats", {})
            range_stats = report.get("cgm_range_stats", {})
            raw_readings = report.get("cgm_readings") or []

            readings = [
                GlucoseReading(
                    timestamp=r["device_timestamp"],
                    value=float(r["glucose_mgdl"]),
                )
                for r in raw_readings
                if r.get("glucose_mgdl") is not None
            ] or None

            in_target = float(range_stats.get("in_target_70_180_percent", 0))

            return GlucoseMetrics(
                average_glucose=float(summary.get("average_glucose_mgdl", 0)),
                time_in_range=in_target,
                range=GlucoseRange(
                    below_54=float(range_stats.get("below_54_percent", 0)),
                    below_70=float(range_stats.get("below_70_above_54_percent", 0)),
                    in_target=in_target,
                    above_180=float(range_stats.get("above_180_below_250_percent", 0)),
                    above_250=float(range_stats.get("above_250_percent", 0)),
                ),
                readings=readings,
            )
        except Exception as e:
            print(f"CGM data error: {e}")
            return GlucoseMetrics()

    async def _get_fitness_data(
        self, patient_id: str, selected_date: date
    ) -> FitnessMetrics:
        try:
            report = await self.fitness_report_service.fetch_daily_report(
                patient_id,
                selected_date,
            )

            if not report:
                return FitnessMetrics()

            raw_hourly = report.get("hourly_stats") or []
            hourly_steps = [
                HourlySteps(hour=int(h["hour"]), steps=int(h.get("steps", 0)))
                for h in raw_hourly
                if h.get("hour") is not None
            ] or None

            return FitnessMetrics(
                steps=int(report.get("steps", 0)),
                active_energy=float(report.get("active_energy", 0)),
                active_duration=int(report.get("active_duration", 0)),
                hourly_steps=hourly_steps,
            )
        except Exception as e:
            print(f"Fitness data error: {e}")
            return FitnessMetrics()

    async def _get_sleep_data(
        self, patient_id: str, selected_date: date
    ) -> SleepMetrics:
        try:
            report = await self.sleep_report_service.fetch_daily_report(
                patient_id, selected_date
            )

            if not report:
                return SleepMetrics()

            duration = report.get("duration_analysis", {})
            quality = report.get("quality_analysis", {})

            return SleepMetrics(
                duration=float(duration.get("total_duration", 0)),
                records_count=int(quality.get("sleep_quality", 0)),
            )

        except Exception as e:
            print(f"Sleep data error: {e}")
            return SleepMetrics()

    async def _get_vitals_data(
        self, patient_id: str, selected_date: date
    ) -> VitalsMetrics:
        try:
            query = f"""
            SELECT type, value
            FROM aihealth.vitals_data FINAL
            WHERE patient_id = '{patient_id}'
                AND toDate(time) = '{selected_date}'
                AND type IN ('systolic_bp', 'diastolic_bp', 'resting_heart_rate')
            ORDER BY time DESC
            LIMIT 1 BY type
            """
            rows = self.clickhouse_store.client.execute(query)
            lookup = {r[0]: r[1] for r in rows}

            systolic = lookup.get("systolic_bp")
            diastolic = lookup.get("diastolic_bp")

            rhr_trend = self._fetch_vital_trend(
                patient_id,
                vital_type="resting_heart_rate",
                end_date=selected_date,
                days=7,
            )

            return VitalsMetrics(
                blood_pressure=BloodPressure(
                    systolic=round(systolic, 1) if systolic is not None else None,
                    diastolic=round(diastolic, 1) if diastolic is not None else None,
                ),
                resting_heart_rate=(
                    round(lookup["resting_heart_rate"], 1)
                    if "resting_heart_rate" in lookup
                    else None
                ),
                resting_heart_rate_trend=rhr_trend,
            )
        except Exception as e:
            print(f"Vitals data error: {e}")
            return VitalsMetrics()

    async def _get_weight_trend(
        self, patient_id: str, selected_date: date
    ) -> list[VitalReading] | None:
        try:
            return self._fetch_vital_trend(
                patient_id,
                vital_type="weight",
                end_date=selected_date,
                days=30,
            )
        except Exception as e:
            print(f"Weight trend error: {e}")
            return None

    def _fetch_vital_trend(
        self,
        patient_id: str,
        *,
        vital_type: str,
        end_date: date,
        days: int,
    ) -> list[VitalReading] | None:
        start_date = end_date - timedelta(days=days - 1)
        query = f"""
        SELECT time, value
        FROM aihealth.vitals_data
        WHERE patient_id = '{patient_id}'
            AND type = '{vital_type}'
            AND toDate(time) >= '{start_date}'
            AND toDate(time) <= '{end_date}'
        ORDER BY time
        """
        rows = self.clickhouse_store.client.execute(query)
        readings = [
            VitalReading(timestamp=r[0], value=float(r[1]))
            for r in rows
            if r and r[1] is not None
        ]
        return readings or None

    async def _get_current_weight(
        self,
        patient_id: str,
        selected_date: date,
        session: AsyncSession,
    ) -> Optional[float]:
        query = f"""
        SELECT value FROM aihealth.vitals_data
        WHERE patient_id = '{patient_id}'
            AND type = 'weight'
            AND toDate(time) <= '{selected_date}'
        ORDER BY time DESC
        LIMIT 1
        """
        rows = self.clickhouse_store.client.execute(query)
        return float(rows[0][0]) if rows else None

    async def _get_previous_day_summary(
        self,
        patient_id: str,
        selected_date: date,
    ) -> PreviousDaySummary:
        yesterday = selected_date - timedelta(days=1)
        try:
            cgm_report, fitness_report, sleep_report = await asyncio.gather(
                self.cgm_report_service.fetch_daily_report(patient_id, yesterday),
                self.fitness_report_service.fetch_daily_report(patient_id, yesterday),
                self.sleep_report_service.fetch_daily_report(patient_id, yesterday),
            )
        except Exception as e:
            print(f"Previous day summary error: {e}")
            return PreviousDaySummary()

        steps: int | None = None
        if fitness_report:
            hourly = fitness_report.get("hourly_stats") or []
            if hourly:
                current_hour = datetime.now().hour
                steps = sum(
                    int(h.get("steps", 0))
                    for h in hourly
                    if h.get("hour") is not None and int(h["hour"]) < current_hour
                )
            else:
                raw_steps = fitness_report.get("steps")
                steps = int(raw_steps) if raw_steps is not None else None

        sleep_duration: float | None = None
        if sleep_report:
            duration = sleep_report.get("duration_analysis", {}).get("total_duration")
            sleep_duration = float(duration) if duration is not None else None

        average_glucose: float | None = None
        time_in_range: float | None = None
        if cgm_report:
            summary = cgm_report.get("cgm_summary_stats", {})
            range_stats = cgm_report.get("cgm_range_stats", {})
            avg = summary.get("average_glucose_mgdl")
            tir = range_stats.get("in_target_70_180_percent")
            average_glucose = float(avg) if avg is not None else None
            time_in_range = float(tir) if tir is not None else None

        return PreviousDaySummary(
            steps=steps,
            sleep_duration=sleep_duration,
            average_glucose=average_glucose,
            time_in_range=time_in_range,
        )
