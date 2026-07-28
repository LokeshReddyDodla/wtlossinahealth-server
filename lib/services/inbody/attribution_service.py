"""InBody scan-attribution store.

One document per scan (``inbody_scan_analyses``): the health agent's read of
what drove the body-composition change between this scan and the previous
one. The background job writes; the API reads.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import UUID

from motor.motor_asyncio import AsyncIOMotorCollection


class InbodyAttributionService:
    def __init__(self, analyses_collection: AsyncIOMotorCollection) -> None:
        self.analyses_collection = analyses_collection

    @staticmethod
    def _clean(doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if doc:
            doc.pop("_id", None)
        return doc

    async def get_for_report(
        self, patient_id: UUID, report_id: UUID
    ) -> Optional[Dict[str, Any]]:
        return self._clean(
            await self.analyses_collection.find_one(
                {
                    "patient_id": str(patient_id),
                    "report_id": str(report_id),
                }
            )
        )

    async def get_latest(
        self, patient_id: UUID
    ) -> Optional[Dict[str, Any]]:
        return self._clean(
            await self.analyses_collection.find_one(
                {"patient_id": str(patient_id)},
                sort=[("generated_at", -1)],
            )
        )

    async def mark_generating(
        self, patient_id: UUID, report_id: UUID
    ) -> None:
        await self._upsert(
            patient_id, report_id, {"status": "generating", "error": None}
        )

    async def mark_failed(
        self, patient_id: UUID, report_id: UUID, error: str
    ) -> None:
        await self._upsert(
            patient_id, report_id, {"status": "failed", "error": error[:500]}
        )

    async def save(
        self,
        patient_id: UUID,
        report_id: UUID,
        *,
        analysis_text: str,
        previous_report_id: Optional[str],
        period: Optional[Dict[str, Optional[str]]],
        deltas: Dict[str, Any],
        is_baseline: bool = False,
    ) -> None:
        await self._upsert(
            patient_id,
            report_id,
            {
                "status": "completed",
                "error": None,
                "analysis_text": analysis_text,
                "previous_report_id": previous_report_id,
                "period": period,
                "deltas": deltas,
                "is_baseline": is_baseline,
                "generated_at": datetime.now(timezone.utc),
            },
        )

    async def _upsert(
        self, patient_id: UUID, report_id: UUID, fields: Dict[str, Any]
    ) -> None:
        now = datetime.now(timezone.utc)
        await self.analyses_collection.update_one(
            {
                "patient_id": str(patient_id),
                "report_id": str(report_id),
            },
            {
                "$set": {
                    "patient_id": str(patient_id),
                    "report_id": str(report_id),
                    "updated_at": now,
                    **fields,
                },
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )
