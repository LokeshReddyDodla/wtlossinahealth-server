"""Aggregates one patient-local day of health data into a typed snapshot.

Pulls from every store the platform records into: Postgres (meals, workouts,
manual glucose, medications, habits, patient profile), ClickHouse (synced
steps/energy, CGM, weight vitals) and MongoDB (InBody reports, GLP-1
settings). Every block is independently optional — a missing source is
reported via ``data_coverage``, never fabricated.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from loguru import logger
from motor.motor_asyncio import AsyncIOMotorCollection
from sqlalchemy import and_, func, select
from sqlalchemy.orm import selectinload

from lib.core.clickhouse_store import ClickHouseStore
from lib.core.postgres_store import PostgresStore
from lib.models.patient import Patient
from lib.models.patient_alcohol_consumption import PatientAlcoholConsumption
from lib.models.patient_daily_activity import PatientDailyActivity
from lib.models.patient_eating_habit import PatientEatingHabit
from lib.models.patient_meal import PatientMeal
from lib.models.patient_medication import PatientMedication
from lib.models.patient_sleep_habit import PatientSleepHabit
from lib.models.patient_smbg import PatientSMBG
from lib.models.patient_smoking_habit import PatientSmokingHabit
from lib.models.patient_workout import PatientWorkout
from lib.models.weight_loss_agent import WeightLossAgentEnrollment
from lib.schemas.weightloss_agent.holistic import (
    FitnessDaily,
    Glp1Snapshot,
    GlucoseDaily,
    HabitsSnapshot,
    HolisticDailySnapshot,
    InbodyBaseline,
    MealSnapshot,
    MealsDaily,
    MedicationSnapshot,
    MedicationsSnapshot,
    PatientContext,
    WorkoutSnapshot,
)

DEFAULT_TIMEZONE = "Asia/Kolkata"

GLUCOSE_SPIKE_MGDL = 180
GLUCOSE_LOW_MGDL = 70


class HolisticDataService:
    """Read-only aggregation of a patient's day across all data stores."""

    def __init__(
        self,
        postgres_store: PostgresStore,
        clickhouse_store: ClickHouseStore,
        inbody_reports_collection: AsyncIOMotorCollection,
        glp1_settings_collection: AsyncIOMotorCollection,
    ) -> None:
        self.postgres_store = postgres_store
        self.clickhouse_store = clickhouse_store
        self.inbody_reports_collection = inbody_reports_collection
        self.glp1_settings_collection = glp1_settings_collection

    # ------------------------------------------------------------------
    # Patient context
    # ------------------------------------------------------------------

    async def get_patient_context(self, patient_id: UUID) -> PatientContext:
        """Profile + enrollment targets, used as the header of every LLM prompt."""

        async with self.postgres_store.get_session() as session:
            patient = await session.get(Patient, patient_id)
            enrollment_result = await session.execute(
                select(WeightLossAgentEnrollment).where(
                    and_(
                        WeightLossAgentEnrollment.patient_id == patient_id,
                        WeightLossAgentEnrollment.is_active.is_(True),
                    )
                )
            )
            enrollment = enrollment_result.scalars().first()

        if not patient:
            logger.warning(
                "holistic: patient {} not found while building context", patient_id
            )
            return PatientContext(patient_id=str(patient_id))

        age = None
        if patient.dob:
            today = date.today()
            age = (
                today.year
                - patient.dob.year
                - ((today.month, today.day) < (patient.dob.month, patient.dob.day))
            )

        return PatientContext(
            patient_id=str(patient_id),
            first_name=patient.first_name,
            age=age,
            gender=patient.gender,
            height_cm=patient.height_cm or patient.height,
            timezone=self.resolve_timezone(patient),
            current_weight_kg=await self._latest_weight(patient_id)
            or patient.weight_kg
            or patient.weight,
            target_weight_kg=enrollment.target_weight_kg if enrollment else None,
            target_bmi=enrollment.target_bmi if enrollment else None,
            program_goals=enrollment.program_goals if enrollment else None,
            enrollment_date=(
                enrollment.enrollment_date.date().isoformat()
                if enrollment and enrollment.enrollment_date
                else None
            ),
        )

    @staticmethod
    def resolve_timezone(patient: Optional[Patient]) -> str:
        if patient is None:
            return DEFAULT_TIMEZONE
        for candidate in (patient.timezone, patient.locale):
            if not candidate:
                continue
            try:
                ZoneInfo(candidate)
                return candidate
            except Exception:
                continue
        return DEFAULT_TIMEZONE

    async def get_patient_timezone(self, patient_id: UUID) -> str:
        async with self.postgres_store.get_session() as session:
            patient = await session.get(Patient, patient_id)
        return self.resolve_timezone(patient)

    # ------------------------------------------------------------------
    # Daily snapshot
    # ------------------------------------------------------------------

    async def get_daily_snapshot(
        self, patient_id: UUID, target_date: date
    ) -> HolisticDailySnapshot:
        """Collect one patient-local day across every source."""

        logger.info(
            "holistic: building daily snapshot patient={} date={}",
            patient_id,
            target_date,
        )

        meals = await self._collect_meals(patient_id, target_date)
        fitness = await self._collect_fitness(patient_id, target_date)
        glucose = await self._collect_glucose(patient_id, target_date)
        medications = await self._collect_medications(patient_id, target_date)
        habits = await self._collect_habits(patient_id)
        weight_kg = await self._weight_on_date(patient_id, target_date)

        coverage = [
            name
            for name, block in (
                ("meals", meals),
                ("fitness", fitness),
                ("glucose", glucose),
                ("medications", medications),
                ("habits", habits),
                ("weight", weight_kg),
            )
            if block is not None
        ]

        logger.info(
            "holistic: snapshot ready patient={} date={} coverage={}",
            patient_id,
            target_date,
            coverage,
        )

        return HolisticDailySnapshot(
            patient_id=str(patient_id),
            date=target_date.isoformat(),
            meals=meals,
            fitness=fitness,
            glucose=glucose,
            medications=medications,
            habits=habits,
            weight_kg=weight_kg,
            data_coverage=coverage,
        )

    async def get_snapshot_range(
        self, patient_id: UUID, start_date: date, end_date: date
    ) -> List[HolisticDailySnapshot]:
        snapshots: List[HolisticDailySnapshot] = []
        current = start_date
        while current <= end_date:
            snapshots.append(await self.get_daily_snapshot(patient_id, current))
            current += timedelta(days=1)
        return snapshots

    # ------------------------------------------------------------------
    # Meals (Postgres)
    # ------------------------------------------------------------------

    async def _collect_meals(
        self, patient_id: UUID, target_date: date
    ) -> Optional[MealsDaily]:
        try:
            async with self.postgres_store.get_session() as session:
                result = await session.execute(
                    select(PatientMeal)
                    .where(
                        and_(
                            PatientMeal.patient_id == patient_id,
                            func.date(PatientMeal.date) == target_date,
                        )
                    )
                    .options(
                        selectinload(PatientMeal.total_macro_nutritional_value),
                        selectinload(PatientMeal.total_micro_nutritional_value),
                    )
                    .order_by(PatientMeal.time)
                )
                meals = result.scalars().all()
        except Exception as exc:
            logger.error(
                "holistic: meal collection failed patient={} date={}: {}",
                patient_id,
                target_date,
                exc,
            )
            return None

        if not meals:
            return None

        snapshots: List[MealSnapshot] = []
        totals: Dict[str, float] = {}

        def _accumulate(key: str, value: Optional[float]) -> Optional[float]:
            if value is None:
                return None
            totals[key] = totals.get(key, 0.0) + value
            return value

        for meal in meals:
            macro = meal.total_macro_nutritional_value
            snapshots.append(
                MealSnapshot(
                    meal_id=str(meal.id),
                    name=meal.name,
                    type=meal.type,
                    slot=meal.slot,
                    time=meal.time.isoformat() if meal.time else None,
                    calories=_accumulate("calories", macro.calories if macro else None),
                    proteins=_accumulate("proteins", macro.proteins if macro else None),
                    carbohydrates=_accumulate(
                        "carbohydrates", macro.carbohydrates if macro else None
                    ),
                    simple_carbs=_accumulate(
                        "simple_carbs", macro.simple_carbs if macro else None
                    ),
                    complex_carbs=_accumulate(
                        "complex_carbs", macro.complex_carbs if macro else None
                    ),
                    fats=_accumulate("fats", macro.fats if macro else None),
                    fiber=_accumulate("fiber", macro.fiber if macro else None),
                    ai_insight=meal.ai_insight,
                )
            )

        return MealsDaily(
            meals_count=len(snapshots),
            total_calories=totals.get("calories"),
            total_proteins=totals.get("proteins"),
            total_carbohydrates=totals.get("carbohydrates"),
            total_simple_carbs=totals.get("simple_carbs"),
            total_complex_carbs=totals.get("complex_carbs"),
            total_fats=totals.get("fats"),
            total_fiber=totals.get("fiber"),
            meals=snapshots,
        )

    # ------------------------------------------------------------------
    # Fitness (ClickHouse synced + Postgres manual workouts)
    # ------------------------------------------------------------------

    async def _collect_fitness(
        self, patient_id: UUID, target_date: date
    ) -> Optional[FitnessDaily]:
        steps = None
        active_energy = None
        active_duration = None
        try:
            query = """
            SELECT
                SUM(CASE WHEN type = 'STEPS' THEN value ELSE 0 END) AS total_steps,
                SUM(CASE WHEN type = 'ACTIVE_ENERGY_BURNED' THEN value ELSE 0 END) AS total_active_energy,
                SUM(dateDiff('minute', start_datetime, end_datetime)) AS total_active_duration
            FROM aihealth.fitness_data
            WHERE patient_id = %(patient_id)s
                AND start_datetime >= %(start)s
                AND end_datetime <= %(end)s
            """
            rows = self.clickhouse_store.client.execute(
                query,
                {
                    "patient_id": str(patient_id),
                    "start": f"{target_date.isoformat()} 00:00:00",
                    "end": f"{target_date.isoformat()} 23:59:59",
                },
            )
            if rows:
                raw_steps, raw_energy, raw_duration = rows[0]
                if raw_steps:
                    steps = int(raw_steps)
                if raw_energy:
                    active_energy = float(raw_energy)
                if raw_duration:
                    active_duration = int(raw_duration)
        except Exception as exc:
            logger.error(
                "holistic: fitness query failed patient={} date={}: {}",
                patient_id,
                target_date,
                exc,
            )

        workouts: List[WorkoutSnapshot] = []
        try:
            async with self.postgres_store.get_session() as session:
                result = await session.execute(
                    select(PatientWorkout)
                    .where(
                        and_(
                            PatientWorkout.patient_id == patient_id,
                            PatientWorkout.date == target_date,
                        )
                    )
                    .options(selectinload(PatientWorkout.exercises))
                )
                for workout in result.scalars().all():
                    workouts.append(
                        WorkoutSnapshot(
                            duration_minutes=workout.duration_minutes,
                            calories_burned=workout.calories_burned,
                            exercises=[
                                ex.exercise_name
                                for ex in (workout.exercises or [])
                                if ex.exercise_name
                            ],
                        )
                    )
        except Exception as exc:
            logger.error(
                "holistic: workout query failed patient={} date={}: {}",
                patient_id,
                target_date,
                exc,
            )

        if steps is None and active_energy is None and not workouts:
            return None

        return FitnessDaily(
            steps=steps,
            active_energy_kcal=active_energy,
            active_duration_min=active_duration,
            workouts=workouts,
        )

    # ------------------------------------------------------------------
    # Glucose (ClickHouse CGM, Postgres SMBG fallback)
    # ------------------------------------------------------------------

    async def _collect_glucose(
        self, patient_id: UUID, target_date: date
    ) -> Optional[GlucoseDaily]:
        try:
            query = """
            SELECT
                count() AS readings,
                avg(glucose_level) AS avg_glucose,
                min(glucose_level) AS min_glucose,
                max(glucose_level) AS max_glucose,
                countIf(glucose_level > %(spike)s) AS spikes,
                countIf(glucose_level < %(low)s) AS lows,
                countIf(glucose_level >= %(low)s AND glucose_level <= %(spike)s) AS in_range
            FROM aihealth.cgm_data
            WHERE patient_id = %(patient_id)s
                AND toDate(time) = %(day)s
            """
            rows = self.clickhouse_store.client.execute(
                query,
                {
                    "patient_id": str(patient_id),
                    "day": target_date.isoformat(),
                    "spike": GLUCOSE_SPIKE_MGDL,
                    "low": GLUCOSE_LOW_MGDL,
                },
            )
            if rows and rows[0][0]:
                readings, avg_g, min_g, max_g, spikes, lows, in_range = rows[0]
                return GlucoseDaily(
                    source="cgm",
                    readings_count=int(readings),
                    average_mgdl=round(float(avg_g), 1) if avg_g else None,
                    min_mgdl=float(min_g) if min_g else None,
                    max_mgdl=float(max_g) if max_g else None,
                    time_in_range_percent=(
                        round(100.0 * int(in_range) / int(readings), 1)
                        if readings
                        else None
                    ),
                    spikes_above_180=int(spikes),
                    lows_below_70=int(lows),
                )
        except Exception as exc:
            logger.error(
                "holistic: CGM query failed patient={} date={}: {}",
                patient_id,
                target_date,
                exc,
            )

        # No CGM rows for the day — fall back to manual finger-prick readings.
        try:
            async with self.postgres_store.get_session() as session:
                result = await session.execute(
                    select(PatientSMBG.glucose_level).where(
                        and_(
                            PatientSMBG.patient_id == patient_id,
                            func.date(PatientSMBG.reading_time) == target_date,
                        )
                    )
                )
                values = [float(v) for v in result.scalars().all()]
        except Exception as exc:
            logger.error(
                "holistic: SMBG query failed patient={} date={}: {}",
                patient_id,
                target_date,
                exc,
            )
            return None

        if not values:
            return None

        in_range = [v for v in values if GLUCOSE_LOW_MGDL <= v <= GLUCOSE_SPIKE_MGDL]
        return GlucoseDaily(
            source="smbg",
            readings_count=len(values),
            average_mgdl=round(sum(values) / len(values), 1),
            min_mgdl=min(values),
            max_mgdl=max(values),
            time_in_range_percent=round(100.0 * len(in_range) / len(values), 1),
            spikes_above_180=len([v for v in values if v > GLUCOSE_SPIKE_MGDL]),
            lows_below_70=len([v for v in values if v < GLUCOSE_LOW_MGDL]),
        )

    # ------------------------------------------------------------------
    # Medications (Postgres) + GLP-1 settings (Mongo)
    # ------------------------------------------------------------------

    async def _collect_medications(
        self, patient_id: UUID, target_date: date
    ) -> Optional[MedicationsSnapshot]:
        meds: List[MedicationSnapshot] = []
        try:
            async with self.postgres_store.get_session() as session:
                result = await session.execute(
                    select(PatientMedication).where(
                        and_(
                            PatientMedication.patient_id == patient_id,
                            PatientMedication.status == "active",
                            PatientMedication.start_date <= target_date,
                        )
                    )
                )
                for med in result.scalars().all():
                    if med.end_date and med.end_date < target_date:
                        continue
                    meds.append(
                        MedicationSnapshot(
                            name=med.name,
                            strength=med.strength,
                            purpose=med.purpose,
                            food_timing=med.food_timing,
                            doses=med.doses or [],
                            schedule=med.schedule,
                        )
                    )
        except Exception as exc:
            logger.error(
                "holistic: medication query failed patient={}: {}", patient_id, exc
            )

        glp1 = await self._collect_glp1(patient_id, target_date)

        if not meds and glp1 is None:
            return None
        return MedicationsSnapshot(active_medications=meds, glp1=glp1)

    async def _collect_glp1(
        self, patient_id: UUID, target_date: date
    ) -> Optional[Glp1Snapshot]:
        try:
            settings = await self.glp1_settings_collection.find_one(
                {"user_id": str(patient_id)}
            )
        except Exception as exc:
            logger.error(
                "holistic: GLP-1 settings lookup failed patient={}: {}",
                patient_id,
                exc,
            )
            return None

        if not settings or not settings.get("injection_date"):
            return None

        try:
            injection_date = date.fromisoformat(str(settings["injection_date"])[:10])
        except ValueError:
            return None

        frequency = settings.get("injection_frequency_days")
        days_since = (target_date - injection_date).days
        days_until = None
        if frequency:
            # Injection cadence repeats — project the most recent cycle boundary.
            days_until = frequency - (days_since % frequency) if days_since >= 0 else None

        return Glp1Snapshot(
            injection_date=injection_date.isoformat(),
            injection_frequency_days=frequency,
            days_since_last_injection=days_since if days_since >= 0 else None,
            days_until_next_injection=days_until,
        )

    # ------------------------------------------------------------------
    # Habits (Postgres, slow-changing)
    # ------------------------------------------------------------------

    async def _collect_habits(self, patient_id: UUID) -> Optional[HabitsSnapshot]:
        try:
            async with self.postgres_store.get_session() as session:
                eating = (
                    await session.execute(
                        select(PatientEatingHabit).where(
                            PatientEatingHabit.patient_id == patient_id
                        )
                    )
                ).scalars().first()
                sleep = (
                    await session.execute(
                        select(PatientSleepHabit).where(
                            PatientSleepHabit.patient_id == patient_id
                        )
                    )
                ).scalars().first()
                smoking = (
                    await session.execute(
                        select(PatientSmokingHabit).where(
                            PatientSmokingHabit.patient_id == patient_id
                        )
                    )
                ).scalars().first()
                alcohol = (
                    await session.execute(
                        select(PatientAlcoholConsumption).where(
                            PatientAlcoholConsumption.patient_id == patient_id
                        )
                    )
                ).scalars().first()
                activity = (
                    await session.execute(
                        select(PatientDailyActivity).where(
                            PatientDailyActivity.patient_id == patient_id
                        )
                    )
                ).scalars().first()
        except Exception as exc:
            logger.error(
                "holistic: habits query failed patient={}: {}", patient_id, exc
            )
            return None

        if not any([eating, sleep, smoking, alcohol, activity]):
            return None

        return HabitsSnapshot(
            meals_per_day=eating.meals_per_day if eating else None,
            snacks_count=eating.snacks_count if eating else None,
            dietary_preferences=list(eating.dietary_preferences or []) if eating else [],
            cuisine_preferences=list(eating.cuisine_preferences or []) if eating else [],
            average_sleep_hours=sleep.average_sleep_hours if sleep else None,
            sleep_quality=sleep.sleep_quality if sleep else None,
            smokes=smoking.smoke_status if smoking else None,
            consumes_alcohol=alcohol.consume_alcohol if alcohol else None,
            alcohol_frequency=alcohol.frequency if alcohol else None,
            activity_level=activity.activity_level if activity else None,
        )

    # ------------------------------------------------------------------
    # Weight (ClickHouse vitals)
    # ------------------------------------------------------------------

    async def _weight_on_date(
        self, patient_id: UUID, target_date: date
    ) -> Optional[float]:
        try:
            rows = self.clickhouse_store.client.execute(
                """
                SELECT value FROM aihealth.vitals_data
                WHERE patient_id = %(patient_id)s
                    AND type = 'weight'
                    AND toDate(time) = %(day)s
                ORDER BY time DESC
                LIMIT 1
                """,
                {"patient_id": str(patient_id), "day": target_date.isoformat()},
            )
            return float(rows[0][0]) if rows else None
        except Exception as exc:
            logger.error(
                "holistic: weight query failed patient={} date={}: {}",
                patient_id,
                target_date,
                exc,
            )
            return None

    async def _latest_weight(self, patient_id: UUID) -> Optional[float]:
        try:
            rows = self.clickhouse_store.client.execute(
                """
                SELECT value FROM aihealth.vitals_data
                WHERE patient_id = %(patient_id)s AND type = 'weight'
                ORDER BY time DESC
                LIMIT 1
                """,
                {"patient_id": str(patient_id)},
            )
            return float(rows[0][0]) if rows else None
        except Exception as exc:
            logger.error(
                "holistic: latest weight query failed patient={}: {}",
                patient_id,
                exc,
            )
            return None

    # ------------------------------------------------------------------
    # InBody baseline (Mongo)
    # ------------------------------------------------------------------

    async def get_inbody_baseline(
        self, enrollment_id: UUID
    ) -> Optional[InbodyBaseline]:
        try:
            report = await self.inbody_reports_collection.find_one(
                {"enrollment_id": str(enrollment_id)}, sort=[("report_date", -1)]
            )
        except Exception as exc:
            logger.error(
                "holistic: inbody lookup failed enrollment={}: {}",
                enrollment_id,
                exc,
            )
            return None

        if not report:
            return None

        lookup: Dict[str, Dict[str, Any]] = {}
        for measurement in report.get("measurements") or []:
            key = str(measurement.get("measurement_type") or "").strip().lower()
            key = key.replace(" ", "_").replace("-", "_")
            if key and key not in lookup:
                lookup[key] = measurement

        def _value(*keys: str) -> Optional[float]:
            for key in keys:
                measurement = lookup.get(key)
                if measurement and measurement.get("value") is not None:
                    try:
                        return float(measurement["value"])
                    except (TypeError, ValueError):
                        continue
            return None

        abnormal = [
            str(h.get("indicator_name") or h.get("indicator_type") or "unknown")
            for h in (report.get("health_indicators") or [])
            if h.get("is_abnormal")
        ]

        report_date = report.get("report_date")
        return InbodyBaseline(
            report_id=report.get("report_id"),
            report_date=(
                report_date.isoformat()
                if isinstance(report_date, (date, datetime))
                else (str(report_date) if report_date else None)
            ),
            inbody_score=report.get("inbody_score")
            or (report.get("sections") or {}).get("inbody_score"),
            bmr_kcal=_value("basal_metabolic_rate", "bmr"),
            body_fat_percent=_value(
                "body_fat_percentage",
                "percentage_body_fat",
                "percent_body_fat",
                "body_fat",
            ),
            skeletal_muscle_mass_kg=_value(
                "skeletal_muscle_mass", "muscle_mass", "skeletal_muscle"
            ),
            visceral_fat_level=_value("visceral_fat_level", "visceral_fat"),
            abnormal_indicators=abnormal,
        )
