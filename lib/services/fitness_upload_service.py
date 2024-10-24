from datetime import datetime
from typing import List, Union

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
        dateFrom, dateTo, source = (
            FitnessUploadUtils.flatten_and_extract_dates(fitness_data)
        )

        if not dateFrom or not dateTo or not source:
            # No data to process
            return None

        await self.delete_existing_data(dateFrom, dateTo, source)
        await self.insert_new_data(fitness_data)
        await self.update_last_sync(dateTo)

        # Commit the session to save all changes
        await self.postgres_session.commit()

        return dateTo

    async def delete_existing_data(
        self,
        dateFrom: datetime,
        dateTo: datetime,
        source: str,
    ):
        # Delete data from ClickHouse
        self.clickhouse_store.delete_existing_fitness_data(
            "aihealth.fitness_data",
            self.patient_id,
            dateFrom.strftime("%Y-%m-%d %H:%M:%S"),
            dateTo.strftime("%Y-%m-%d %H:%M:%S"),
            source,
        )

        # Delete data from PostgreSQL (PatientSMBG, PatientVitals, PatientSleep)
        await self.postgres_session.execute(
            delete(PatientSMBG)
            .where(PatientSMBG.patient_id == self.patient_id)
            .where(PatientSMBG.reading_time.between(dateFrom, dateTo))
            .where(PatientSMBG.source == source)
        )

        await self.postgres_session.execute(
            delete(PatientVital)
            .where(PatientVital.patient_id == self.patient_id)
            .where(PatientVital.test_time.between(dateFrom, dateTo))
            .where(PatientVital.source == source)
        )

        await self.postgres_session.execute(
            delete(PatientSleep)
            .where(PatientSleep.patient_id == self.patient_id)
            .where(PatientSleep.sleep_start_time.between(dateFrom, dateTo))
            .where(PatientSleep.source == source)
        )

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
