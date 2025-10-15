import hashlib
import logging
from datetime import datetime
from typing import Dict, Any
from openai import AsyncOpenAI

from qdrant_client.http.models import (
    PointStruct,
    PointIdsList,
    Filter,
    FieldCondition,
    MatchValue,
)

from lib.services.smbg_vector_service.smbg_text_repr_builder import (
    SMBGTextReprBuilder,
)
from lib.utils.vector_utils import embed_text

logger = logging.getLogger(__name__)


class SMBGVectorService:
    def __init__(self, qdrant_store, collection_name: str = "patient_data"):
        self.qdrant_store = qdrant_store
        self.collection_name = collection_name
        self.openai_client = AsyncOpenAI()

    async def upsert_smbg(
        self,
        patient_id: str,
        reading_id: str,
        reading: Dict[str, Any],
        patient_age: int,
        patient_gender: str,
    ):
        try:
            async with self.qdrant_store.get_client() as client:
                point = await self._build_point(
                    patient_id,
                    reading_id,
                    reading,
                    patient_age,
                    patient_gender,
                )

                embedding = await embed_text(point["text"])
                if embedding:
                    await client.upsert(
                        collection_name=self.collection_name,
                        points=[
                            PointStruct(
                                id=point["id"],
                                vector=embedding,
                                payload=point["payload"],
                            )
                        ],
                    )

                return {"points_created": 1}

        except Exception as e:
            logger.error(f"❌ Failed to upsert SMBG reading {reading_id}: {e}")
            raise

    def _generate_point_id(self, reading_id: str) -> str:
        return hashlib.md5(reading_id.encode()).hexdigest()

    async def _build_point(
        self,
        patient_id: str,
        reading_id: str,
        reading: Dict[str, Any],
        patient_age: int,
        patient_gender: str,
    ) -> Dict[str, Any]:
        dt = datetime.fromisoformat(str(reading["reading_time"]))
        uploaded_at = reading.get("uploaded_at")
        uploaded_at_ms = (
            int(datetime.fromisoformat(str(uploaded_at)).timestamp() * 1000)
            if uploaded_at
            else None
        )

        glucose_mgdl = float(reading.get("glucose_mgdl", 0))
        reading_type = reading.get(
            "type", ""
        ).lower()  # e.g., "pre-meal", "post-meal", "fasting"
        notes = reading.get("notes", "")
        source = reading.get("source", "app")

        payload = {
            "patient_id": patient_id,
            "patient_age": patient_age,
            "patient_gender": patient_gender,
            "reading_id": reading_id,
            "data_type": "smbg",
            "start_time": int(dt.timestamp() * 1000),
            "end_time": int(dt.timestamp() * 1000),
            "date": dt.date().isoformat(),
            "day_of_week": dt.weekday(),
            "is_weekend": dt.weekday() >= 5,
            "week_number": dt.isocalendar()[1],
            "hour": dt.hour,
            "month": dt.month,
            "time_of_day_bucket": self._bucket_time(dt.hour),
            "glucose_mgdl": glucose_mgdl,
            "reading_type": reading_type,
            "reading_time": int(dt.timestamp() * 1000),
            "notes": notes,
            "source": source,
            "uploaded_at": uploaded_at_ms,
        }

        # Build text representation for embedding
        text_repr = SMBGTextReprBuilder.build(reading)
        payload["text_repr"] = text_repr

        return {
            "id": self._generate_point_id(reading_id),
            "text": text_repr,
            "payload": payload,
        }

    def _bucket_time(self, hour: int) -> str:
        if 6 <= hour < 12:
            return "morning"
        elif 12 <= hour < 18:
            return "afternoon"
        elif 18 <= hour < 24:
            return "evening"
        else:
            return "night"

    async def delete_smbg_vector(self, reading_id: str):
        try:
            point_id = self._generate_point_id(reading_id)
            async with self.qdrant_store.get_client() as client:
                await client.delete(
                    collection_name=self.collection_name,
                    points_selector=PointIdsList(points=[point_id]),
                )
            logger.info(f"🗑️ Deleted vector for SMBG reading {reading_id}")
        except Exception as e:
            logger.error(f"❌ Failed to delete SMBG vector {reading_id}: {e}")

    async def delete_smbg_vectors_for_patient(self, patient_id: str):
        try:
            async with self.qdrant_store.get_client() as client:
                await client.delete(
                    collection_name=self.collection_name,
                    points_selector=Filter(
                        must=[
                            FieldCondition(
                                key="patient_id",
                                match=MatchValue(value=patient_id),
                            ),
                            FieldCondition(
                                key="data_type",
                                match=MatchValue(value="smbg"),
                            ),
                        ]
                    ),
                )
            logger.info(
                f"🧹 Deleted all SMBG vectors for patient {patient_id}"
            )
        except Exception as e:
            logger.error(
                f"❌ Failed to delete SMBG vectors for patient {patient_id}: {e}"
            )
