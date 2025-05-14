from datetime import datetime
from io import StringIO
from typing import List

import pandas as pd
from lib.core.postgres_store import PostgresStore
from lib.models.patient_connected_app import PatientConnectedApp
from sqlalchemy.ext.asyncio import AsyncSession

from lib.tasks.cgm_tasks import generate_cgm_reports_for_patient
from lib.utils.cgm_utils import CGMDataUtils
from lib.utils.http_exceptions import raise_http_exception
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from lib.utils.postgres_session_decorator import with_postgres_session


class CGMUploadService:
    def __init__(
        self,
        clickhouse_store,
        postgres_store: PostgresStore,
    ):
        self.clickhouse_store = clickhouse_store
        self.postgres_store = postgres_store

    @with_postgres_session
    async def parse_and_upload_libreview_raw_csv_data(
        self,
        patient_id: str,
        file_contents: bytes,
        *,
        postgres_session: AsyncSession
    ):
        try:
            # Decode and read the CSV file
            decoded = file_contents.decode("utf-8")
            df = pd.read_csv(StringIO(decoded), skiprows=2)

            # Convert timestamps without changing the timezone
            df["Device Timestamp"] = pd.to_datetime(
                df["Device Timestamp"], format="%d-%m-%Y %I:%M %p"
            ).dt.tz_localize(None)

            # Determine time range for deletion
            start_time = df["Device Timestamp"].min()
            end_time = df["Device Timestamp"].max()

            # Delete existing CGM data in the range
            self.clickhouse_store.delete_existing_cgm_data(
                "aihealth.cgm_data", patient_id, start_time, end_time
            )

            # Prepare new data
            data_points = []
            for _, row in df.iterrows():
                if pd.notna(row["Scan Glucose mg/dL"]):
                    record_type = "scan"
                    glucose_level = int(row["Scan Glucose mg/dL"])
                elif pd.notna(row["Historic Glucose mg/dL"]):
                    record_type = "historic"
                    glucose_level = int(row["Historic Glucose mg/dL"])
                else:
                    continue

                data_points.append(
                    {
                        "patient_id": str(patient_id),
                        "time": row["Device Timestamp"].strftime(
                            "%Y-%m-%dT%H:%M:%S"
                        ),
                        "glucose_level": glucose_level,
                        "record_type": record_type,
                    }
                )

            cgm_data_utils = CGMDataUtils(self.clickhouse_store)
            cgm_report_periods = cgm_data_utils.generate_all_report_periods(df)
            print("==> cgm_report_periods: ", cgm_report_periods)

            # Write data to ClickHouse
            self.clickhouse_store.write_data("aihealth.cgm_data", data_points)

            # Update last_sync_timestamp for the connected app if it exists
            connected_app_result = await postgres_session.execute(
                select(PatientConnectedApp)
                .where(PatientConnectedApp.patient_id == patient_id)
                .options(selectinload(PatientConnectedApp.libreview))
            )
            connected_app = connected_app_result.scalars().first()
            if connected_app and connected_app.libreview:
                connected_app.libreview.last_sync_timestamp = datetime.now()
                await postgres_session.commit()

            generate_cgm_reports_for_patient.delay(
                patient_id, cgm_report_periods
            )

        except Exception as e:
            raise_http_exception(
                status_code=500,
                message="Failed to upload CGM data",
                detail=str(e),
            )
