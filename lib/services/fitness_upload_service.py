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
from lib.tasks.fitness_tasks import generate_fitness_reports_for_patient
from rest_server.patients.fitness.api_schema import FitnessDataRequest


class FitnessUploadService:
    def __init__(
        self,
        clickhouse_store,
        fitness_sync_store,
        postgres_session,
    ):
        self.clickhouse_store = clickhouse_store
        self.fitness_sync_store = fitness_sync_store
        self.postgres_session = postgres_session

    async def process_fitness_data(
        self, patient_id: str, fitness_data: FitnessDataRequest
    ) -> datetime:
        start_datetime, end_datetime = (
            fitness_data.start_datetime,
            fitness_data.end_datetime,
        )

        await self.delete_existing_data(
            patient_id, start_datetime, end_datetime
        )
        await self.insert_new_data(patient_id, fitness_data)
        await self.update_last_sync(patient_id, end_datetime)

        # Commit the session to save all changes
        await self.postgres_session.commit()

        # Trigger report generation asynchronously
        generate_fitness_reports_for_patient.delay(
            patient_id, start_datetime, end_datetime
        )

        return end_datetime

    async def delete_existing_data(
        self,
        patient_id: str,
        start_datetime: datetime,
        end_datetime: datetime,
        source_name: Optional[str] = None,
    ):
        # Delete data from ClickHouse
        self.clickhouse_store.delete_existing_fitness_data(
            "aihealth.fitness_data",
            patient_id,
            start_datetime.strftime("%Y-%m-%d %H:%M:%S"),
            end_datetime.strftime("%Y-%m-%d %H:%M:%S"),
            source_name,
        )

        smbg_query = delete(PatientSMBG).where(
            PatientSMBG.patient_id == patient_id,
            PatientSMBG.reading_time.between(start_datetime, end_datetime),
        )
        vital_query = delete(PatientVital).where(
            PatientVital.patient_id == patient_id,
            PatientVital.test_time.between(start_datetime, end_datetime),
        )
        sleep_query = delete(PatientSleep).where(
            PatientSleep.patient_id == patient_id,
            PatientSleep.sleep_start_time.between(
                start_datetime, end_datetime
            ),
        )

        # If a specific source_name is provided, filter by source_name
        if source_name:
            smbg_query = smbg_query.where(
                PatientSMBG.source_name == source_name
            )
            vital_query = vital_query.where(
                PatientVital.source_name == source_name
            )
            sleep_query = sleep_query.where(
                PatientSleep.source_name == source_name
            )
        else:
            # Exclude manual sources by default if no specific source_name is provided
            smbg_query = smbg_query.where(PatientSMBG.source_name != "manual")
            vital_query = vital_query.where(
                PatientVital.source_name != "manual"
            )
            sleep_query = sleep_query.where(
                PatientSleep.source_name != "manual"
            )

        # Execute queries
        await self.postgres_session.execute(smbg_query)
        await self.postgres_session.execute(vital_query)
        await self.postgres_session.execute(sleep_query)

    async def insert_new_data(
        self, patient_id: str, fitness_data: FitnessDataRequest
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
                "start_datetime": parse(item.start_datetime)
                .replace(tzinfo=None)
                .strftime("%Y-%m-%dT%H:%M:%S"),
                "end_datetime": parse(item.end_datetime)
                .replace(tzinfo=None)
                .strftime("%Y-%m-%dT%H:%M:%S"),
            }
            for item in fitness_data.steps + fitness_data.active_energy_burned
        ]
        self.clickhouse_store.write_data("aihealth.fitness_data", data_points)

        # Insert data into PatientVitals, PatientSMBG, PatientSleep, etc.
        vitals = [
            PatientVital(
                patient_id=patient_id,
                diastolic_bp=diastolic_item.value,
                systolic_bp=systolic_item.value,
                test_time=parse(diastolic_item.start_datetime).replace(
                    tzinfo=None
                ),
                source_name=diastolic_item.source_name,
                source_platform=diastolic_item.source_platform,
            )
            for diastolic_item, systolic_item in zip(
                fitness_data.blood_pressure_diastolic,
                fitness_data.blood_pressure_systolic,
            )
        ]

        for item in fitness_data.heart_rate:
            vitals.append(
                PatientVital(
                    patient_id=patient_id,
                    heart_rate=item.value,
                    test_time=parse(item.start_datetime).replace(tzinfo=None),
                    source_name=item.source_name,
                    source_platform=item.source_platform,
                )
            )

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

        sleep_records = [
            PatientSleep(
                patient_id=patient_id,
                source_name=item.source_name,
                source_platform=item.source_platform,
                sleep_start_time=parse(item.start_datetime).replace(
                    tzinfo=None
                ),
                sleep_end_time=parse(item.end_datetime).replace(tzinfo=None),
                sleep_duration=item.value,
                type=sleep_type,
            )
            for sleep_type, sleep_data in [
                ("sleep_in_bed", fitness_data.sleep_in_bed),
                ("sleep_deep", fitness_data.sleep_deep),
            ]
            for item in sleep_data
        ]

        self.postgres_session.add_all(vitals + smbg_records + sleep_records)

    async def update_last_sync(self, patient_id: str, dateTo: datetime):
        fitness_sync_key = f"fitness_sync:{patient_id}"

        # Set or update the sync timestamp in Redis
        self.fitness_sync_store.set_key(
            fitness_sync_key,
            value=dateTo.isoformat(),
        )
