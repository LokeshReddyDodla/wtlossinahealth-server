from datetime import datetime
from io import BytesIO, StringIO
from typing import List, Tuple
import zipfile

import pandas as pd
from lib.core.postgres_store import PostgresStore
from lib.models.patient_connected_app import PatientConnectedApp
from sqlalchemy.ext.asyncio import AsyncSession

from lib.tasks.cgm_tasks import trigger_cgm_report_generation_for_periods
from lib.utils.cgm_utils import CGMDataUtils
from lib.utils.http_exceptions import raise_http_exception
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from lib.utils.libre_view_sensor_report_generator import (
    SensorLifecycleReportGenerator,
)
from lib.utils.postgres_session_decorator import with_postgres_session
from xlrd.biffh import XLRDError


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
        postgres_session: AsyncSession,
    ):
        try:
            # Decode and read the CSV file
            decoded = file_contents.decode("utf-8")
            df = pd.read_csv(StringIO(decoded), skiprows=2)

            # Convert timestamps without changing the timezone
            df["Device Timestamp"] = pd.to_datetime(
                df["Device Timestamp"],
                format="%d-%m-%Y %I:%M %p",
                errors="coerce",
            ).dt.tz_localize(None)
            df = df.dropna(subset=["Device Timestamp"])

            # Determine time range for deletion
            start_time = df["Device Timestamp"].min()
            end_time = df["Device Timestamp"].max()

            # Delete existing CGM data in the range
            self.clickhouse_store.delete_existing_cgm_data(
                "aihealth.cgm_data",
                patient_id,
                start_time,
                end_time,
                "libreview",
            )

            # Prepare new data
            data_points = []
            for _, row in df.iterrows():
                glucose_val = None
                record_type = None

                if pd.notna(row["Scan Glucose mg/dL"]):
                    record_type = "scan"
                    glucose_val = int(row["Scan Glucose mg/dL"])
                elif pd.notna(row["Historic Glucose mg/dL"]):
                    record_type = "historic"
                    glucose_val = int(row["Historic Glucose mg/dL"])
                else:
                    continue

                data_points.append(
                    {
                        "patient_id": str(patient_id),
                        "time": row[
                            "Device Timestamp"
                        ],  # .strftime("%Y-%m-%dT%H:%M:%S")
                        "glucose_level": glucose_val,
                        "record_type": record_type,
                        "source": "libreview",
                    }
                )

            # cgm_data_utils = CGMDataUtils(self.clickhouse_store)
            # cgm_report_periods = cgm_data_utils.generate_all_report_periods(df)
            # print("==> cgm_report_periods: ", cgm_report_periods)

            generator = SensorLifecycleReportGenerator(df)
            reports = generator.generate_reports()
            report_periods: List[Tuple[datetime, datetime]] = [
                (
                    r["start"],
                    r["end"],
                )
                for idx, r in enumerate(reports, start=1)
            ]
            # print("==> report_periods: ", report_periods)
            # for r in reports:
            #     print(
            #         r["start"],
            #         "→",
            #         r["end"],
            #         "days:",
            #         r["duration_h"] / 24,
            #         "coverage:",
            #         round(r["coverage"], 2),
            #     )

            # Insert into ClickHouse
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

            trigger_cgm_report_generation_for_periods.delay(
                patient_id, report_periods
            )  # type: ignore

            print(
                f"✅ Uploaded CGM data for {patient_id} "
                f"({len(data_points)} records, {len(report_periods)} periods)."
            )

        except Exception as e:
            raise_http_exception(
                status_code=500,
                message="Failed to upload CGM data",
                detail=str(e),
            )

    @with_postgres_session
    async def parse_and_upload_sinocare_excel_data(
        self,
        patient_id: str,
        file_contents: bytes,
        *,
        postgres_session: AsyncSession,
    ):
        try:
            # Read Excel or CSV
            try:
                df_raw = pd.read_excel(
                    BytesIO(file_contents), engine="xlrd", skiprows=3
                )
            except (zipfile.BadZipFile, XLRDError):
                df_raw = pd.read_csv(BytesIO(file_contents), skiprows=3)

            # Normalize column names
            df_raw.columns = [str(c).strip().lower() for c in df_raw.columns]

            # Ensure required columns exist
            required_cols = ["s/n", "time point", "value", "units"]
            if not set(required_cols).issubset(df_raw.columns):
                raise ValueError(
                    "Sinocare Excel does not contain the expected columns"
                )

            df = df_raw[required_cols].copy()

            # Convert timestamp
            df["timestamp"] = pd.to_datetime(
                df["time point"], errors="coerce"
            ).dt.tz_localize(None)
            df = df.dropna(subset=["timestamp"])

            # Normalize units
            df["units"] = df["units"].str.strip().str.lower()

            # Convert to mg/dL dynamically
            def convert_to_mgdl(value, unit):
                try:
                    val = float(value)
                except Exception:
                    return None
                if unit in ["mmol/l", "mmol"]:
                    return round(val * 18)
                elif unit in ["mg/dl", "mg"]:
                    return round(val)
                return None

            df["glucose_mgdl"] = df.apply(
                lambda row: convert_to_mgdl(row["value"], row["units"]), axis=1  # type: ignore
            )  # type: ignore
            df = df.dropna(subset=["glucose_mgdl"])
            df["glucose_mgdl"] = df["glucose_mgdl"].astype(int)

            # Determine deletion window
            start_time = df["timestamp"].min()
            end_time = df["timestamp"].max()

            # Delete existing records
            self.clickhouse_store.delete_existing_cgm_data(
                "aihealth.cgm_data",
                patient_id,
                start_time,
                end_time,
                "sinocare",
            )

            # Prepare ClickHouse data
            data_points = []
            for _, row in df.iterrows():
                data_points.append(
                    {
                        "patient_id": str(patient_id),
                        "time": row["timestamp"],
                        "glucose_level": row["glucose_mgdl"],
                        "record_type": "historic",
                        "source": "sinocare",
                    }
                )

            # Insert new readings
            self.clickhouse_store.write_data("aihealth.cgm_data", data_points)

            # Generate lifecycle report
            lifecycle_df = pd.DataFrame(
                {
                    "Device Timestamp": df["timestamp"],
                    "Historic Glucose mg/dL": df["glucose_mgdl"],
                }
            )

            generator = SensorLifecycleReportGenerator(lifecycle_df)
            reports = generator.generate_reports()
            report_periods = [(r["start"], r["end"]) for r in reports]

            # Update last sync
            connected_app_result = await postgres_session.execute(
                select(PatientConnectedApp)
                .where(PatientConnectedApp.patient_id == patient_id)
                .options(selectinload(PatientConnectedApp.sinocare))
            )
            connected_app = connected_app_result.scalars().first()
            if connected_app and connected_app.sinocare:
                connected_app.sinocare.last_sync_timestamp = datetime.now()
                await postgres_session.commit()

            # Trigger async CGM report generation
            trigger_cgm_report_generation_for_periods.delay(
                patient_id, report_periods
            )

            print(
                f"✅ Uploaded Sinocare data for {patient_id} "
                f"({len(data_points)} records, {len(report_periods)} periods)"
            )

        except Exception as e:
            raise_http_exception(
                status_code=500,
                message="Failed to upload Sinocare Excel CGM data",
                detail=str(e),
            )
