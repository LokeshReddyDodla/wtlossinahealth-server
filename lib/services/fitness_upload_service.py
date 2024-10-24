from datetime import datetime
from typing import List, Optional, Union

from dateutil.parser import parse
from sqlalchemy import delete
from sqlalchemy.future import select
from sqlalchemy.orm import Session

from lib.models.patient import Patient
from lib.models.patient_sleep import PatientSleep
from lib.models.patient_smbg import PatientSMBG
from lib.models.patient_vital import PatientVital
from lib.utils.fitness_upload_utils import FitnessUploadUtils
from rest_server.patients.fitness.api_schema import FitnessDataRequest


class FitnessUploadService:
    def __init__(
        self,
        clickhouse_store,
        fitness_sync_store,
        postgres_session,
        patient_id,
    ):
        self.clickhouse_store = clickhouse_store
        self.fitness_sync_store = fitness_sync_store
        self.postgres_session = postgres_session
        self.patient_id = patient_id

    async def process_fitness_data(self, fitness_data: FitnessDataRequest):
        dateFrom, dateTo = (
            fitness_data.dateFrom,
            fitness_data.dateTo,
        )

        await self.delete_existing_data(dateFrom, dateTo)
        await self.insert_new_data(fitness_data)
        await self.update_last_sync(dateTo)

        # Commit the session to save all changes
        await self.postgres_session.commit()

        return dateTo

    async def delete_existing_data(
        self,
        dateFrom: datetime,
        dateTo: datetime,
        source: Optional[str] = None,
    ):
        # Delete data from ClickHouse
        self.clickhouse_store.delete_existing_fitness_data(
            "aihealth.fitness_data",
            self.patient_id,
            dateFrom.strftime("%Y-%m-%d %H:%M:%S"),
            dateTo.strftime("%Y-%m-%d %H:%M:%S"),
            source,
        )

        smbg_query = delete(PatientSMBG).where(
            PatientSMBG.patient_id == self.patient_id,
            PatientSMBG.reading_time.between(dateFrom, dateTo),
        )
        vital_query = delete(PatientVital).where(
            PatientVital.patient_id == self.patient_id,
            PatientVital.test_time.between(dateFrom, dateTo),
        )
        sleep_query = delete(PatientSleep).where(
            PatientSleep.patient_id == self.patient_id,
            PatientSleep.sleep_start_time.between(dateFrom, dateTo),
        )

        # If a specific source is provided, filter by source
        if source:
            smbg_query = smbg_query.where(PatientSMBG.source == source)
            vital_query = vital_query.where(PatientVital.source == source)
            sleep_query = sleep_query.where(PatientSleep.source == source)
        else:
            # Exclude manual sources by default if no specific source is provided
            smbg_query = smbg_query.where(PatientSMBG.source != "manual")
            vital_query = vital_query.where(PatientVital.source != "manual")
            sleep_query = sleep_query.where(PatientSleep.source != "manual")

        # Execute queries
        await self.postgres_session.execute(smbg_query)
        await self.postgres_session.execute(vital_query)
        await self.postgres_session.execute(sleep_query)

    async def insert_new_data(self, fitness_data: FitnessDataRequest):
        # Insert data into ClickHouse (steps and active_energy_burned)
        data_points = [
            {
                "patient_id": self.patient_id,
                "type": item.type,
                "source": item.source,
                "unit": item.unit,
                "value": float(item.value),
                "date_from": parse(item.dateFrom)
                .replace(tzinfo=None)
                .strftime("%Y-%m-%dT%H:%M:%S"),
                "date_to": parse(item.dateTo)
                .replace(tzinfo=None)
                .strftime("%Y-%m-%dT%H:%M:%S"),
            }
            for item in fitness_data.steps + fitness_data.active_energy_burned
        ]
        self.clickhouse_store.write_data("aihealth.fitness_data", data_points)

        # Insert data into PatientVitals, PatientSMBG, PatientSleep, etc.
        vitals = [
            PatientVital(
                patient_id=self.patient_id,
                diastolic_bp=diastolic_item.value,
                systolic_bp=systolic_item.value,
                test_time=parse(diastolic_item.dateFrom).replace(tzinfo=None),
                source=diastolic_item.source,
            )
            for diastolic_item, systolic_item in zip(
                fitness_data.blood_pressure_diastolic,
                fitness_data.blood_pressure_systolic,
            )
        ]

        for item in fitness_data.heart_rate:
            vitals.append(
                PatientVital(
                    patient_id=self.patient_id,
                    heart_rate=item.value,
                    test_time=parse(item.dateFrom).replace(tzinfo=None),
                    source=item.source,
                )
            )

        smbg_records = [
            PatientSMBG(
                patient_id=self.patient_id,
                glucose_level=item.value,
                reading_time=parse(item.dateFrom).replace(tzinfo=None),
                source=item.source,
                type="Unspecified",
            )
            for item in fitness_data.blood_glucose
        ]

        sleep_records = [
            PatientSleep(
                patient_id=self.patient_id,
                source=item.source,
                sleep_start_time=parse(item.dateFrom).replace(tzinfo=None),
                sleep_end_time=parse(item.dateTo).replace(tzinfo=None),
                sleep_duration=item.value,
            )
            for item in fitness_data.sleep_in_bed
        ]

        self.postgres_session.add_all(vitals + smbg_records + sleep_records)

    async def update_last_sync(self, dateTo: datetime):
        fitness_sync_key = f"fitness_sync:{self.patient_id}"

        # Set or update the sync timestamp in Redis
        self.fitness_sync_store.set_key(
            fitness_sync_key,
            value=dateTo.isoformat(),
        )
