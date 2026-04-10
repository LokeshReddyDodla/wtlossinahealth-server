"""Vector service for active medication data."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from qdrant_client.http.models import PointStruct

from lib.core.qdrant_store import QdrantStore
from lib.utils.vector_utils import embed_text

from ..base import BaseVectorService
from ..utils.exceptions import VectorServiceError

logger = logging.getLogger(__name__)


class MedicationVectorService(BaseVectorService):
    """Vectorizes all of a patient's medications (current + past) as a single Qdrant point."""

    def __init__(
        self, qdrant_store: QdrantStore, collection_name: str = "patient_data"
    ):
        super().__init__(qdrant_store, collection_name)

    async def upsert_medications_vector(
        self,
        patient_id: str,
        medications: list[dict[str, Any]],
        patient_age: int,
        patient_gender: str,
    ) -> dict[str, int]:
        """Upsert a single vector point representing all medications (current + past)."""
        try:
            text = self._build_text_repr(medications)
            if not text:
                return {"points_created": 0}

            point_id = self._generate_simple_point_id(f"{patient_id}_medications")

            now = datetime.now()
            payload = {
                "patient_id": patient_id,
                "patient_age": patient_age,
                "patient_gender": patient_gender,
                "data_type": "medication",
                "text_repr": text,
                "medication_names": [m["name"] for m in medications],
                "medication_count": len(medications),
                "conditions": [
                    m["purpose"]
                    for m in medications
                    if m.get("purpose")
                ],
                "date": now.strftime("%Y-%m-%d"),
                "month": now.month,
                "week_number": now.isocalendar()[1],
                "day_of_week": now.isoweekday(),
                "is_weekend": now.isoweekday() >= 6,
                "time_of_day_bucket": ["all_day"],
                "start_time": int(now.timestamp() * 1000),
                "end_time": int(now.timestamp() * 1000),
                "vector_updated_at": int(now.timestamp() * 1000),
            }

            embedding = await embed_text(text)
            if not embedding:
                return {"points_created": 0}

            async with self.qdrant_store.get_client() as client:
                await client.upsert(
                    collection_name=self.collection_name,
                    points=[
                        PointStruct(
                            id=point_id,
                            vector=embedding,
                            payload=payload,
                        )
                    ],
                )
            return {"points_created": 1}
        except Exception as e:
            logger.error(
                "Failed to upsert medication vector for %s: %s",
                patient_id,
                e,
            )
            raise VectorServiceError(
                f"Failed to upsert medication vector: {e}",
                service_name=self.__class__.__name__,
            ) from e

    async def delete_medications_vector(self, patient_id: str) -> None:
        """Remove the medication vector for a patient."""
        try:
            from qdrant_client.models import PointIdsList

            point_id = self._generate_simple_point_id(
                f"{patient_id}_medications"
            )
            async with self.qdrant_store.get_client() as client:
                await client.delete(
                    collection_name=self.collection_name,
                    points_selector=PointIdsList(points=[point_id]),
                )
        except Exception as e:
            logger.error(
                "Failed to delete medication vector for %s: %s",
                patient_id,
                e,
            )

    @staticmethod
    def _build_text_repr(medications: list[dict[str, Any]]) -> str:
        """Build human-readable text for embedding."""
        if not medications:
            return ""

        parts: list[str] = []
        for med in medications:
            name = med.get("name", "Unknown")
            strength = med.get("strength", "")
            status = med.get("status", "active")

            is_current = status in ("active", "as_needed", "paused", "scheduled")
            if status == "scheduled":
                verb = "will start taking"
            elif status == "paused":
                verb = "takes (currently paused)"
            elif status == "as_needed":
                verb = "takes as needed"
            elif is_current:
                verb = "takes"
            else:
                verb = "took"
            line = f"Patient {verb} {name}"
            if strength:
                line += f" {strength}"

            # Dose schedule
            doses = med.get("doses", [])
            if doses:
                slots = [d["slot"] for d in doses]
                line += f" ({' and '.join(slots)})"

            food = med.get("food_timing")
            if food:
                line += f", {food}"

            purpose = med.get("purpose")
            if purpose:
                line += f" for {purpose}"

            if not is_current:
                start = med.get("start_date")
                end = med.get("end_date")
                if start and end:
                    line += f". Taken from {start} to {end}. Status: {status}."
                elif end:
                    line += f". Ended {end}. Status: {status}."
                else:
                    line += f". Status: {status}."
            elif med.get("end_date"):
                line += f". Course ends {med['end_date']}."
            else:
                line += ". Ongoing."

            parts.append(line)

        return " ".join(parts)
