from datetime import datetime
from typing import Optional

from dateutil.parser import parse
from sqlalchemy import delete

from lib.core.postgres_store import PostgresStore
from lib.models.patient_smbg import PatientSMBG
from lib.workers.tasks.fitness.enqueue import (
    enqueue_process_fitness_upload_sync,
)
from lib.workers.tasks.sleep.enqueue import enqueue_process_sleep_upload_sync
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

        await self.delete_existing_data(
            patient_id, start_datetime, end_datetime, postgres_session=postgres_session
        )
        await self.insert_new_data(
            patient_id, fitness_data, postgres_session=postgres_session
        )
        await self.update_last_sync(patient_id, end_datetime)

        # Commit the session to save all changes
        await postgres_session.commit()

        # Trigger report generation asynchronously
        enqueue_process_fitness_upload_sync(patient_id, start_datetime, end_datetime)

        enqueue_process_sleep_upload_sync(patient_id, start_datetime, end_datetime)

        return end_datetime

    @with_postgres_session
    async def delete_existing_data(
        self,
        patient_id: str,
        start_datetime: datetime,
        end_datetime: datetime,
        source_name: Optional[str] = None,
        *,
        postgres_session: AsyncSession,
    ):
        smbg_query = delete(PatientSMBG).where(
            PatientSMBG.patient_id == patient_id,
            PatientSMBG.reading_time.between(start_datetime, end_datetime),
        )

        if source_name:
            smbg_query = smbg_query.where(PatientSMBG.source_name == source_name)
        else:
            smbg_query = smbg_query.where(PatientSMBG.source_name != "manual")

        await postgres_session.execute(smbg_query)

    @with_postgres_session
    async def insert_new_data(
        self,
        patient_id: str,
        fitness_data: FitnessDataRequest,
        *,
        postgres_session: AsyncSession,
    ):
        # Insert data into ClickHouse (steps and active_energy_burned)
        data_points = [
            {
                "patient_id": patient_id,
                "type": item.type,
                "source_name": item.source_name,
                "source_platform": item.source_platform,
                "unit": item.unit,
                "value": float(item.value),
                "start_datetime": parse(item.start_datetime).replace(
                    tzinfo=None
                ),  # .strftime("%Y-%m-%dT%H:%M:%S")
                "end_datetime": parse(item.end_datetime).replace(
                    tzinfo=None
                ),  # .strftime("%Y-%m-%dT%H:%M:%S")
            }
            for item in fitness_data.steps + fitness_data.active_energy_burned
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

        if vitals_data_points:
            self.clickhouse_store.write_data("aihealth.vitals_data", vitals_data_points)

        smbg_records = [
            PatientSMBG(
                patient_id=patient_id,
                glucose_level=item.value,
                reading_time=parse(item.start_datetime).replace(tzinfo=None),
                source_name=item.source_name,
                source_platform=item.source_platform,
                type="Unspecified",
            )
            for item in fitness_data.blood_glucose
        ]

        postgres_session.add_all(smbg_records)

    async def update_last_sync(self, patient_id: str, dateTo: datetime):
        fitness_sync_key = f"fitness_sync:{patient_id}"

        # Set or update the sync timestamp in Redis
        self.fitness_sync_store.set_key(
            fitness_sync_key,
            value=dateTo.isoformat(),
        )
