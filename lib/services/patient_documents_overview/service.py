"""Patient-level overview of all uploaded medical documents.

One document per patient, recomputed by an arq job after every upload
or delete from either the patient or the doctor side. Holds the
deterministic link_groups + an LLM-generated narrative so both
audiences see the same up-to-date view.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from motor.motor_asyncio import AsyncIOMotorCollection

from lib.schemas.profile_agent_documents import (
    LinkGroup,
    OverviewResponse,
)

logger = logging.getLogger(__name__)


class PatientDocumentsOverviewService:
    def __init__(self, overview_collection: AsyncIOMotorCollection):
        self.collection = overview_collection

    async def ensure_indexes(self) -> None:
        await self.collection.create_index(
            [("patient_id", 1)],
            unique=True,
            name="unique_patient_documents_overview_per_patient",
        )

    async def fetch(self, patient_id: str) -> Optional[OverviewResponse]:
        doc = await self.collection.find_one({"patient_id": patient_id})
        if not doc:
            return None
        return _to_response(doc)

    async def upsert(
        self,
        *,
        patient_id: str,
        summary_text: str,
        key_observations: List[str],
        link_groups: List[LinkGroup],
        source_document_ids: List[str],
        latest_document_date: Optional[datetime],
        document_count: int,
    ) -> None:
        now = datetime.utcnow()
        payload = {
            "patient_id": patient_id,
            "summary_text": summary_text,
            "key_observations": key_observations,
            "link_groups": [g.model_dump(mode="json") for g in link_groups],
            "source_document_ids": source_document_ids,
            "latest_document_date": latest_document_date,
            "document_count": document_count,
            "updated_at": now,
        }
        await self.collection.update_one(
            {"patient_id": patient_id},
            {"$set": payload},
            upsert=True,
        )


def _to_response(doc: Dict[str, Any]) -> OverviewResponse:
    return OverviewResponse(
        patient_id=str(doc["patient_id"]),
        summary_text=doc.get("summary_text"),
        key_observations=list(doc.get("key_observations") or []),
        link_groups=[LinkGroup(**g) for g in (doc.get("link_groups") or [])],
        source_document_ids=list(doc.get("source_document_ids") or []),
        latest_document_date=doc.get("latest_document_date"),
        document_count=int(doc.get("document_count") or 0),
        updated_at=doc.get("updated_at"),
    )
