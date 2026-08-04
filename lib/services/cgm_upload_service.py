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

from lib.ai_foundation.agents.proactive_monitor.contracts import EventTrigger
from lib.core.postgres_store import PostgresStore
from lib.models.patient_connected_app import PatientConnectedApp
from lib.services.cgm_threshold_detector import detect_latest_crossing
from lib.utils.http_exceptions import raise_http_exception
from lib.utils.libre_view_sensor_report_generator import SensorLifecycleReportGenerator
from lib.utils.postgres_session_decorator import with_postgres_session
from lib.workers.arq.config import Queues
from lib.workers.arq.redis import enqueue_job
from lib.workers.tasks.cgm.enqueue import enqueue_cgm_report_generation_async


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

            end_time = df["Device Timestamp"].max()

            data_points = self._extract_libreview_data_points(df, patient_id)
            report_periods = self._generate_report_periods(df)

            self.clickhouse_store.write_data("aihealth.cgm_data", data_points)

            await self._enqueue_meal_report_refresh(patient_id, data_points)
            await self._update_last_sync(postgres_session, patient_id, "libreview", end_time)

            await enqueue_cgm_report_generation_async(patient_id, report_periods)

            # Gamification hook (fire-and-forget)
            try:
                from uuid import UUID as _UUID
                from lib.core.container import container
                from lib.services.gamification.event_handler import GamificationEventHandler
                handler = container.resolve(GamificationEventHandler)
                await handler.on_glucose_synced(_UUID(patient_id))
            except Exception:
                pass

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
    async def write_readings(
        self,
        patient_id: str,
        rows: List[dict],
        source: str,
        *,
        postgres_session: AsyncSession,
    ) -> int:
        """Write already-normalized CGM rows to ClickHouse.

        For live-streaming sources (e.g. LibreLinkUp follower API) that hand
        over rolling-window data without a CSV. Bypasses CSV parsing and
        sensor-lifecycle report generation (those belong to the full-history
        CSV path). Updates `last_cgm_reading_at` only — callers that track
        their own per-source sync timestamp should write it themselves.
        """
        if not rows:
            return 0

        self.clickhouse_store.write_data("aihealth.cgm_data", rows)

        await self._enqueue_meal_report_refresh(patient_id, rows)

        latest_reading_time = max(r["time"] for r in rows)
        await self._update_last_sync(
            postgres_session, patient_id, source, latest_reading_time
        )

        # Gamification hook (fire-and-forget)
        try:
            from uuid import UUID as _UUID
            from lib.core.container import container
            from lib.services.gamification.event_handler import GamificationEventHandler
            handler = container.resolve(GamificationEventHandler)
            await handler.on_glucose_synced(_UUID(patient_id))
        except Exception:
            pass

        # Proactive threshold-crossed event (fire-and-forget). The detector
        # emits facts; downstream LLM produces the patient-facing response.
        try:
            crossing = detect_latest_crossing(rows)
            if crossing is not None:
                ts_iso = crossing.time.isoformat()
                await enqueue_job(
                    "handle_proactive_event",
                    patient_id,
                    EventTrigger.CGM_THRESHOLD_CROSSED.value,
                    {
                        "kind": crossing.kind.value,
                        "value": crossing.value,
                        "unit": "mg/dL",
                        "time": ts_iso,
                    },
                    _job_id=f"insight:{EventTrigger.CGM_THRESHOLD_CROSSED.value}:{patient_id}:{ts_iso}:{crossing.kind.value}",
                    _defer_by=0,
                    _queue_name=Queues.INSTANT,
                )
        except Exception as exc:
            logger.warning(
                f"Failed to enqueue CGM threshold event for {patient_id}: {exc}"
            )

        logger.info(
            f"Wrote {len(rows)} {source} CGM rows for {patient_id} "
            f"(latest: {latest_reading_time})"
        )
        return len(rows)

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

            end_time = df["timestamp"].max()

            data_points = self._extract_sinocare_data_points(df, patient_id)

            self.clickhouse_store.write_data("aihealth.cgm_data", data_points)

            await self._enqueue_meal_report_refresh(patient_id, data_points)

            lifecycle_df = pd.DataFrame(
                {
                    "Device Timestamp": df["timestamp"],
                    "Historic Glucose mg/dL": df["glucose_mgdl"],
                }
            )
            report_periods = self._generate_report_periods(lifecycle_df)

            await self._update_last_sync(postgres_session, patient_id, "sinocare", end_time)

            await enqueue_cgm_report_generation_async(patient_id, report_periods)

            # Gamification hook (fire-and-forget)
            try:
                from uuid import UUID as _UUID
                from lib.core.container import container
                from lib.services.gamification.event_handler import GamificationEventHandler
                handler = container.resolve(GamificationEventHandler)
                await handler.on_glucose_synced(_UUID(patient_id))
            except Exception:
                pass

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

    @with_postgres_session
    async def parse_and_upload_linx_csv_data(
        self,
        patient_id: str,
        file_contents: bytes,
        *,
        postgres_session: AsyncSession,
    ):
        try:
            df = self._parse_linx_file(file_contents)

            end_time = df["timestamp"].max()

            data_points = self._extract_linx_data_points(df, patient_id)
            self.clickhouse_store.write_data("aihealth.cgm_data", data_points)

            await self._enqueue_meal_report_refresh(patient_id, data_points)

            lifecycle_df = pd.DataFrame(
                {
                    "Device Timestamp": df["timestamp"],
                    "Historic Glucose mg/dL": df["glucose_mgdl"],
                }
            )
            report_periods = self._generate_report_periods(lifecycle_df)

            await self._update_last_sync(postgres_session, patient_id, "linx", end_time)
            await enqueue_cgm_report_generation_async(patient_id, report_periods)

            # Gamification hook (fire-and-forget)
            try:
                from uuid import UUID as _UUID
                from lib.core.container import container
                from lib.services.gamification.event_handler import GamificationEventHandler
                handler = container.resolve(GamificationEventHandler)
                await handler.on_glucose_synced(_UUID(patient_id))
            except Exception:
                pass

            logger.info(
                f"Uploaded Linx data for {patient_id} "
                f"({len(data_points)} records, {len(report_periods)} periods)"
            )

        except Exception as e:
            logger.error(f"Failed to upload Linx data for {patient_id}: {e}")
            raise_http_exception(
                status_code=500,
                message="Failed to upload Linx CSV CGM data",
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

        required_cols = ["time point", "value", "units"]
        if not set(required_cols).issubset(df_raw.columns):
            raise ValueError("Sinocare file missing required columns")

        df = df_raw[required_cols].copy()
        df["timestamp"] = pd.to_datetime(
            df["time point"], dayfirst=True, errors="coerce"
        ).dt.tz_localize(None)
        df = df.dropna(subset=["timestamp"])

        df["units"] = df["units"].str.strip().str.lower()
        df["glucose_mgdl"] = df.apply(
            lambda row: self._convert_to_mgdl(row["value"], row["units"]),  # type: ignore
            axis=1,
        )  # type: ignore
        df = df.dropna(subset=["glucose_mgdl"])
        df["glucose_mgdl"] = df["glucose_mgdl"].astype(int)

        return df

    def _parse_linx_file(self, file_contents: bytes) -> pd.DataFrame:
        """Parse Linx CSV file and normalize data."""
        df_raw = pd.read_csv(BytesIO(file_contents))
        df_raw.columns = [str(c).strip().lower() for c in df_raw.columns]

        time_candidates = ["device_time", "device time", "timestamp", "time"]
        value_candidates = [
            "value(mg/dl)",
            "value (mg/dl)",
            "glucose(mg/dl)",
            "glucose (mg/dl)",
            "value",
        ]

        time_col = next((c for c in time_candidates if c in df_raw.columns), None)
        value_col = next((c for c in value_candidates if c in df_raw.columns), None)

        if not time_col or not value_col:
            raise ValueError(
                "Linx file missing required columns: device_time and value(mg/dL)"
            )

        df = df_raw[[time_col, value_col]].copy()
        df["timestamp"] = pd.to_datetime(
            df[time_col], format="%Y/%m/%d %H:%M", errors="coerce"
        ).dt.tz_localize(None)
        df = df.dropna(subset=["timestamp"])

        df["glucose_mgdl"] = pd.to_numeric(df[value_col], errors="coerce")
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

    def _extract_linx_data_points(self, df: pd.DataFrame, patient_id: str) -> List[dict]:
        """Extract CGM data points from Linx DataFrame."""
        return [
            {
                "patient_id": str(patient_id),
                "time": row["timestamp"],
                "glucose_level": row["glucose_mgdl"],
                "record_type": "historic",
                "source": "linx",
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

    async def _enqueue_meal_report_refresh(
        self, patient_id: str, rows: List[dict]
    ) -> None:
        """Regenerate meal reports for days that just received CGM data, so each
        meal's post-meal excursion reflects late-arriving glucose (live-sync lag,
        later CSV). Deduped per (patient, date, 30-min bucket) since live sources
        sync every 5 min and an excursion settles ~2h after the meal.
        """
        dates = {
            r["time"].date() for r in rows if isinstance(r.get("time"), datetime)
        }
        if not dates:
            return
        now = datetime.now()
        bucket = f"{now:%Y%m%d%H}{now.minute // 30}"
        for d in dates:
            try:
                await enqueue_job(
                    "generate_daily_meal_report",
                    patient_id,
                    d,
                    _job_id=f"meal:report:cgmsync:{patient_id}:{d.isoformat()}:{bucket}",
                    _queue_name=Queues.REPORTS,
                )
            except Exception as exc:
                logger.warning(
                    f"Failed to enqueue meal refresh for {patient_id} on {d}: {exc}"
                )

    async def _update_last_sync(
        self,
        session: AsyncSession,
        patient_id: str,
        source: str,
        latest_reading_time: datetime,
    ) -> None:
        """Update last_sync_timestamp and last_cgm_reading_at for the connected app."""
        attr_map = {
            "libreview": "libreview",
            "librelinkup": "libreview",
            "sinocare": "sinocare",
        }
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
                now = datetime.now()
                source_app.last_cgm_reading_at = latest_reading_time
                # LLU runs every 5 min; don't clobber the CSV-export
                # `last_sync_timestamp` (used for the 3x/day cooldown).
                if source == "librelinkup":
                    source_app.llu_last_sync_timestamp = now
                else:
                    source_app.last_sync_timestamp = now
                await session.commit()
