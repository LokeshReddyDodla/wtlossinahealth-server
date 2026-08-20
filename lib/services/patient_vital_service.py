"""Patient Vital Service."""

from __future__ import annotations

import asyncio

from datetime import datetime, timedelta
from uuid import uuid4

from lib.core.clickhouse_store import ClickHouseStore
from lib.derived import DataDomain, mark_dirty
from lib.schemas.patient_vital import PatientVitalCreate
from lib.services.patient_summary.enum import StaleReason
from lib.utils.patient_summary_stale import mark_summary_stale_and_enqueue
from lib.workers.tasks.vitals.enqueue import enqueue_generate_vital_vector_async

# Vital fields that map to ClickHouse type+value rows
_VITAL_FIELDS: list[str] = [
    "heart_rate", "systolic_bp", "diastolic_bp", "spo2",
    "temperature", "respiratory_rate", "weight",
    "a1c", "creatinine", "ketones",
]


class PatientVitalService:
    def __init__(self, clickhouse_store: ClickHouseStore) -> None:
        self.clickhouse = clickhouse_store

    async def get_patient_vitals(
        self,
        patient_id: str,
        *,
        limit: int = 20,
        offset: int = 0,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> tuple[list[dict], int]:
        """Return vitals newest-first with pagination and optional date filter."""
        return await asyncio.to_thread(
            self.clickhouse.query_vitals,
            patient_id,
            start_time=start_date,
            end_time=end_date,
            limit=limit,
            offset=offset,
        )

    async def get_vitals_summary(
        self,
        patient_id: str,
        start_date: datetime,
        end_date: datetime,
    ) -> list[dict]:
        """Daily avg/min/max/count per vital type."""
        return await asyncio.to_thread(
            self.clickhouse.query_vitals_summary, patient_id, start_date, end_date
        )

    async def get_latest_vitals(
        self, patient_id: str, since: datetime | None = None
    ) -> list[dict]:
        """Most recent reading per vital type, optionally bounded to a window."""
        return await asyncio.to_thread(
            self.clickhouse.query_vitals_latest, patient_id, since=since
        )

    async def get_weight_history(self, patient_id: str, days: int = 60) -> list[dict]:
        """Weight readings over the trailing window, for weight-trend triage."""
        # ClickHouse toDateTime() only accepts second precision.
        end = datetime.utcnow().replace(microsecond=0)
        rows, _ = await asyncio.to_thread(
            self.clickhouse.query_vitals,
            patient_id,
            start_time=end - timedelta(days=days),
            end_time=end,
            types=["weight"],
            limit=200,
        )
        return rows

    async def upload_patient_vital(
        self,
        patient_id: str,
        vital_data: PatientVitalCreate,
    ) -> dict:
        """Write a manual vital entry to ClickHouse.

        Expands each non-null vital field into a separate ClickHouse row
        (type + value), sharing a single vital_id for the group.
        """
        vital_id = uuid4().hex[:12]
        test_time = vital_data.test_time.replace(tzinfo=None)

        rows: list[dict] = []
        for field in _VITAL_FIELDS:
            value = getattr(vital_data, field, None)
            if value is not None:
                rows.append({
                    "patient_id": patient_id,
                    "vital_id": vital_id,
                    "type": field,
                    "value": float(value),
                    "time": test_time,
                    "source_name": vital_data.source_name or "",
                    "source_platform": vital_data.source_platform or "",
                })

        if rows:
            self.clickhouse.write_data("aihealth.vitals_data", rows)
            await mark_dirty(patient_id, DataDomain.VITALS, [test_time.date()])

        # Mark affected summaries as stale
        await mark_summary_stale_and_enqueue(
            patient_id=patient_id,
            target_date=vital_data.test_time.date(),
            stale_reason=StaleReason.DATA_UPDATED,
        )

        # Enqueue Qdrant vector generation
        vital_data_dict = {
            f: getattr(vital_data, f, None) for f in _VITAL_FIELDS
        }
        vital_data_dict.update({
            "test_time": vital_data.test_time,
            "source_name": vital_data.source_name or "",
            "source_platform": vital_data.source_platform or "",
            "uploaded_at": datetime.utcnow(),
        })
        await enqueue_generate_vital_vector_async(
            patient_id=patient_id,
            vital_id=vital_id,
            vital_data=vital_data_dict,
        )

        # Weight sync + gamification (fire-and-forget)
        if vital_data.weight is not None:
            try:
                from lib.utils.sync_profile_weight import sync_profile_weight
                await sync_profile_weight(patient_id, float(vital_data.weight))
            except Exception:
                pass
            try:
                from uuid import UUID as _UUID
                from lib.core.container import container
                from lib.services.gamification.event_handler import GamificationEventHandler
                handler = container.resolve(GamificationEventHandler)
                await handler.on_weight_logged(_UUID(patient_id))
            except Exception:
                pass

        return {"vital_id": vital_id, "rows_written": len(rows)}

    async def delete_vital(self, vital_id: str, patient_id: str) -> None:
        """Delete all rows for a vital_id from ClickHouse."""
        self.clickhouse.delete_vitals_by_vital_id(patient_id, vital_id)
