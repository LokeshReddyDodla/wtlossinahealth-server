"""CGM Upload Service - handles file parsing and data ingestion."""

from datetime import datetime
from io import BytesIO, StringIO
from typing import List
import zipfile

import pandas as pd
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from xlrd.biffh import XLRDError

from lib.core.postgres_store import PostgresStore
from lib.models.patient_connected_app import PatientConnectedApp
from lib.utils.http_exceptions import raise_http_exception
from lib.utils.libre_view_sensor_report_generator import SensorLifecycleReportGenerator
from lib.utils.postgres_session_decorator import with_postgres_session
from lib.workers.tasks.cgm.enqueue import enqueue_cgm_report_generation_sync


class CGMUploadService:
    def __init__(self, clickhouse_store, postgres_store: PostgresStore):
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
            decoded = file_contents.decode("utf-8")
            df = pd.read_csv(StringIO(decoded), skiprows=2)

            df["Device Timestamp"] = pd.to_datetime(
                df["Device Timestamp"],
                format="%d-%m-%Y %I:%M %p",
                errors="coerce",
            ).dt.tz_localize(None)
            df = df.dropna(subset=["Device Timestamp"])

            start_time = df["Device Timestamp"].min()
            end_time = df["Device Timestamp"].max()

            self.clickhouse_store.delete_existing_cgm_data(
                "aihealth.cgm_data", patient_id, start_time, end_time, "libreview"
            )

            data_points = self._extract_libreview_data_points(df, patient_id)
            report_periods = self._generate_report_periods(df)

            self.clickhouse_store.write_data("aihealth.cgm_data", data_points)

            await self._update_last_sync(postgres_session, patient_id, "libreview")

            enqueue_cgm_report_generation_sync(patient_id, report_periods)

            logger.info(
                f"Uploaded LibreView data for {patient_id} "
                f"({len(data_points)} records, {len(report_periods)} periods)"
            )

        except Exception as e:
            logger.error(f"Failed to upload LibreView data for {patient_id}: {e}")
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
            df = self._parse_sinocare_file(file_contents)

            start_time = df["timestamp"].min()
            end_time = df["timestamp"].max()

            self.clickhouse_store.delete_existing_cgm_data(
                "aihealth.cgm_data", patient_id, start_time, end_time, "sinocare"
            )

            data_points = self._extract_sinocare_data_points(df, patient_id)

            self.clickhouse_store.write_data("aihealth.cgm_data", data_points)

            lifecycle_df = pd.DataFrame(
                {
                    "Device Timestamp": df["timestamp"],
                    "Historic Glucose mg/dL": df["glucose_mgdl"],
                }
            )
            report_periods = self._generate_report_periods(lifecycle_df)

            await self._update_last_sync(postgres_session, patient_id, "sinocare")

            enqueue_cgm_report_generation_sync(patient_id, report_periods)

            logger.info(
                f"Uploaded Sinocare data for {patient_id} "
                f"({len(data_points)} records, {len(report_periods)} periods)"
            )

        except Exception as e:
            logger.error(f"Failed to upload Sinocare data for {patient_id}: {e}")
            raise_http_exception(
                status_code=500,
                message="Failed to upload Sinocare Excel CGM data",
                detail=str(e),
            )

    def _extract_libreview_data_points(
        self, df: pd.DataFrame, patient_id: str
    ) -> List[dict]:
        """Extract CGM data points from LibreView DataFrame."""
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
                    "time": row["Device Timestamp"],
                    "glucose_level": glucose_val,
                    "record_type": record_type,
                    "source": "libreview",
                }
            )
        return data_points

    def _parse_sinocare_file(self, file_contents: bytes) -> pd.DataFrame:
        """Parse Sinocare Excel/CSV file and normalize data."""
        try:
            df_raw = pd.read_excel(BytesIO(file_contents), engine="xlrd", skiprows=3)
        except (zipfile.BadZipFile, XLRDError):
            df_raw = pd.read_csv(BytesIO(file_contents), skiprows=3)

        df_raw.columns = [str(c).strip().lower() for c in df_raw.columns]

        required_cols = ["s/n", "time point", "value", "units"]
        if not set(required_cols).issubset(df_raw.columns):
            raise ValueError("Sinocare file missing required columns")

        df = df_raw[required_cols].copy()
        df["timestamp"] = pd.to_datetime(
            df["time point"], errors="coerce"
        ).dt.tz_localize(None)
        df = df.dropna(subset=["timestamp"])

        df["units"] = df["units"].str.strip().str.lower()
        df["glucose_mgdl"] = df.apply(
            lambda row: self._convert_to_mgdl(row["value"], row["units"]),
            axis=1,
        )
        df = df.dropna(subset=["glucose_mgdl"])
        df["glucose_mgdl"] = df["glucose_mgdl"].astype(int)

        return df

    @staticmethod
    def _convert_to_mgdl(value, unit: str) -> int | None:
        """Convert glucose value to mg/dL."""
        try:
            val = float(value)
        except (ValueError, TypeError):
            return None

        if unit in ("mmol/l", "mmol"):
            return round(val * 18)
        elif unit in ("mg/dl", "mg"):
            return round(val)
        return None

    def _extract_sinocare_data_points(
        self, df: pd.DataFrame, patient_id: str
    ) -> List[dict]:
        """Extract CGM data points from Sinocare DataFrame."""
        return [
            {
                "patient_id": str(patient_id),
                "time": row["timestamp"],
                "glucose_level": row["glucose_mgdl"],
                "record_type": "historic",
                "source": "sinocare",
            }
            for _, row in df.iterrows()
        ]

    @staticmethod
    def _generate_report_periods(
        df: pd.DataFrame,
    ):
        """Generate sensor report periods from CGM data."""
        generator = SensorLifecycleReportGenerator(df)
        reports = generator.generate_reports()
        return reports

    async def _update_last_sync(
        self,
        session: AsyncSession,
        patient_id: str,
        source: str,
    ) -> None:
        """Update last_sync_timestamp for the connected app."""
        attr_map = {"libreview": "libreview", "sinocare": "sinocare"}
        attr_name = attr_map.get(source)
        if not attr_name:
            return

        result = await session.execute(
            select(PatientConnectedApp)
            .where(PatientConnectedApp.patient_id == patient_id)
            .options(selectinload(getattr(PatientConnectedApp, attr_name)))
        )
        connected_app = result.scalars().first()

        if connected_app:
            source_app = getattr(connected_app, attr_name, None)
            if source_app:
                source_app.last_sync_timestamp = datetime.now()
                await session.commit()
