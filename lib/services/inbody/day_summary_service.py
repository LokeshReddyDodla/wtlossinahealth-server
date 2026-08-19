"""InBody daily summary store.

The summary itself is a dynamic, health-agent-generated read of the patient's
day, so it lives in MongoDB (``inbody_day_summaries``) — one document per
patient per local day — rather than on the Postgres report row. The
background job writes; the API reads.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, Optional
from uuid import UUID

from motor.motor_asyncio import AsyncIOMotorCollection


class InbodyDaySummaryService:
    def __init__(
        self, summaries_collection: AsyncIOMotorCollection
    ) -> None:
        self.summaries_collection = summaries_collection

    @staticmethod
    def _clean(doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if doc:
            doc.pop("_id", None)
        return doc

    async def get_for_date(
        self, patient_id: UUID, summary_date: date
    ) -> Optional[Dict[str, Any]]:
        return self._clean(
            await self.summaries_collection.find_one(
                {
                    "patient_id": str(patient_id),
                    "summary_date": summary_date.isoformat(),
                }
            )
        )

    async def get_latest(
        self, patient_id: UUID
    ) -> Optional[Dict[str, Any]]:
        return self._clean(
            await self.summaries_collection.find_one(
                {"patient_id": str(patient_id)},
                sort=[("summary_date", -1)],
            )
        )

    async def save(
        self, patient_id: UUID, summary_date: date, summary: str
    ) -> None:
        now = datetime.now(timezone.utc)
        # One doc per patient per day; a re-run refreshes it in place.
        await self.summaries_collection.update_one(
            {
                "patient_id": str(patient_id),
                "summary_date": summary_date.isoformat(),
            },
            {
                "$set": {
                    "patient_id": str(patient_id),
                    "summary_date": summary_date.isoformat(),
                    "summary": summary,
                    "updated_at": now,
                },
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )
