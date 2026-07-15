from datetime import datetime
from dateutil.parser import parse
from sqlalchemy.dialects.postgresql import insert as pg_insert

from lib.core.postgres_store import PostgresStore
from lib.models.patient_smbg import PatientSMBG
from lib.workers.tasks.fitness.enqueue import (
    enqueue_process_fitness_upload_async,
)
from lib.workers.tasks.sleep.enqueue import enqueue_process_sleep_upload_async
from lib.utils.postgres_session_decorator import with_postgres_session
from rest_server.patients.fitness.api_schema import FitnessDataRequest
from sqlalchemy.ext.asyncio import AsyncSession


class FitnessUploadService:
    def __init__(
        self,
        clickhouse_store,
        fitness_sync_store,
        postgres_store: PostgresStore,
    ):
        self.clickhouse_store = clickhouse_store
        self.fitness_sync_store = fitness_sync_store
        self.postgres_store = postgres_store

    @with_postgres_session
    async def process_fitness_data(
        self,
        patient_id: str,
        fitness_data: FitnessDataRequest,
        *,
        postgres_session: AsyncSession,
    ) -> datetime:
        start_datetime, end_datetime = (
            fitness_data.start_datetime,
            fitness_data.end_datetime,
        )

        await self.insert_new_data(
            patient_id, fitness_data, postgres_session=postgres_session
        )
        await self.update_last_sync(patient_id, end_datetime)

        # Commit the session to save all changes
        await postgres_session.commit()

        # Trigger report generation asynchronously
        await enqueue_process_fitness_upload_async(patient_id, start_datetime, end_datetime)

        await enqueue_process_sleep_upload_async(patient_id, start_datetime, end_datetime)

        # Gamification hook (fire-and-forget)
        try:
            from uuid import UUID as _UUID
            from lib.core.container import container
            from lib.services.gamification.event_handler import GamificationEventHandler
            handler = container.resolve(GamificationEventHandler)

            # Sum only today's steps (filter by end_datetime date to exclude multi-day batches)
            steps = None
            if fitness_data.steps:
                today_date = end_datetime.date()
                today_steps = [
                    item for item in fitness_data.steps
                    if parse(item.start_datetime).date() == today_date
                ]
                steps = sum(item.value for item in today_steps) or None

            # Detect workouts
            workout_completed = bool(fitness_data.workouts)

            await handler.on_fitness_synced(
                _UUID(patient_id), steps=steps, workout_completed=workout_completed
            )

            # Glucose via HealthKit
            if fitness_data.blood_glucose:
                await handler.on_glucose_synced(_UUID(patient_id))

            # Weight via HealthKit
            if fitness_data.weight:
                await handler.on_weight_logged(_UUID(patient_id))
        except Exception:
            pass

        return end_datetime

    @with_postgres_session
    async def insert_new_data(
        self,
        patient_id: str,
        fitness_data: FitnessDataRequest,
        *,
        postgres_session: AsyncSession,
    ):
        # Insert fitness data into ClickHouse
        fitness_items = (
            fitness_data.steps
            + fitness_data.active_energy_burned
            + fitness_data.distance_walking_running
            + fitness_data.flights_climbed
            + fitness_data.exercise_time
            + fitness_data.workouts
        )
        data_points = [
            {
                "patient_id": patient_id,
                "type": item.type,
                "source_name": item.source_name,
                "source_platform": item.source_platform,
                "unit": item.unit,
                "value": float(item.value),
                "start_datetime": parse(item.start_datetime).replace(tzinfo=None),
                "end_datetime": parse(item.end_datetime).replace(tzinfo=None),
            }
            for item in fitness_items
        ]
        self.clickhouse_store.write_data("aihealth.fitness_data", data_points)

        # Insert sleep data into ClickHouse
        sleep_data_points = [
            {
                "patient_id": patient_id,
                "type": sleep_type,
                "source_name": item.source_name,
                "source_platform": item.source_platform,
                "sleep_duration": float(item.value),
                "sleep_start_time": parse(item.start_datetime).replace(tzinfo=None),
                "sleep_end_time": parse(item.end_datetime).replace(tzinfo=None),
            }
            for sleep_type, sleep_data in [
                ("sleep_in_bed", fitness_data.sleep_in_bed),
                ("sleep_deep", fitness_data.sleep_deep),
                ("sleep_light", fitness_data.sleep_light),
                ("sleep_rem", fitness_data.sleep_rem),
                ("sleep_awake", fitness_data.sleep_awake),
            ]
            for item in sleep_data
        ]
        self.clickhouse_store.write_data("aihealth.sleep_data", sleep_data_points)

        # Insert vitals into ClickHouse (HR, BP)
        vitals_data_points: list[dict] = []
        for diastolic_item, systolic_item in zip(
            fitness_data.blood_pressure_diastolic,
            fitness_data.blood_pressure_systolic,
        ):
            t = parse(diastolic_item.start_datetime).replace(tzinfo=None)
            vitals_data_points.append({
                "patient_id": patient_id, "type": "diastolic_bp",
                "value": diastolic_item.value, "time": t,
                "source_name": diastolic_item.source_name,
                "source_platform": diastolic_item.source_platform,
            })
            vitals_data_points.append({
                "patient_id": patient_id, "type": "systolic_bp",
                "value": systolic_item.value, "time": t,
                "source_name": systolic_item.source_name,
                "source_platform": systolic_item.source_platform,
            })

        for item in fitness_data.heart_rate:
            vitals_data_points.append({
                "patient_id": patient_id, "type": "heart_rate",
                "value": item.value,
                "time": parse(item.start_datetime).replace(tzinfo=None),
                "source_name": item.source_name,
                "source_platform": item.source_platform,
            })

        for vital_type, vital_data in [
            ("blood_oxygen", fitness_data.blood_oxygen),
            ("resting_heart_rate", fitness_data.resting_heart_rate),
            ("body_temperature", fitness_data.body_temperature),
            ("weight", fitness_data.weight),
            ("respiratory_rate", fitness_data.respiratory_rate),
        ]:
            for item in vital_data:
                vitals_data_points.append({
                    "patient_id": patient_id, "type": vital_type,
                    "value": item.value,
                    "time": parse(item.start_datetime).replace(tzinfo=None),
                    "source_name": item.source_name,
                    "source_platform": item.source_platform,
                })

        if vitals_data_points:
            self.clickhouse_store.write_data("aihealth.vitals_data", vitals_data_points)

        if fitness_data.blood_glucose:
            values = [
                {
                    "patient_id": patient_id,
                    "glucose_level": item.value,
                    "reading_time": parse(item.start_datetime).replace(tzinfo=None),
                    "source_name": item.source_name,
                    "source_platform": item.source_platform,
                    "type": "Unspecified",
                }
                for item in fitness_data.blood_glucose
            ]
            stmt = pg_insert(PatientSMBG).values(values)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_smbg_patient_time_source",
                set_={
                    "glucose_level": stmt.excluded.glucose_level,
                    "source_platform": stmt.excluded.source_platform,
                    "type": stmt.excluded.type,
                },
            )
            await postgres_session.execute(stmt)

    async def update_last_sync(self, patient_id: str, dateTo: datetime):
        fitness_sync_key = f"fitness_sync:{patient_id}"

        # Set or update the sync timestamp in Redis
        self.fitness_sync_store.set_key(
            fitness_sync_key,
            value=dateTo.isoformat(),
        )
