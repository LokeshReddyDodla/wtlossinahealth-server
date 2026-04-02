"""Vector service for sleep check-in, mood entry, and symptom entry data."""

import logging
from datetime import datetime
from typing import Any, Dict

from qdrant_client.http.models import PointStruct

from lib.core.qdrant_store import QdrantStore
from lib.utils.vector_utils import embed_text

from ..base import BaseVectorService
from ..utils.exceptions import VectorServiceError
from .text_builder import CheckinTextReprBuilder

logger = logging.getLogger(__name__)


class CheckinVectorService(BaseVectorService):
    """Service for vectorizing sleep check-in and mood entry data."""

    def __init__(self, qdrant_store: QdrantStore, collection_name: str = "patient_data"):
        super().__init__(qdrant_store, collection_name)

    async def upsert_sleep_vector(
        self,
        patient_id: str,
        sleep_data: Dict[str, Any],
        patient_age: int,
        patient_gender: str,
    ) -> Dict[str, int]:
        try:
            async with self.qdrant_store.get_client() as client:
                point = self._build_sleep_point(
                    patient_id, sleep_data, patient_age, patient_gender,
                )
                embedding = await embed_text(point["text"])
                if embedding:
                    await client.upsert(
                        collection_name=self.collection_name,
                        points=[PointStruct(
                            id=point["id"], vector=embedding, payload=point["payload"],
                        )],
                    )
                return {"points_created": 1}
        except Exception as e:
            logger.error(f"Failed to upsert sleep vector for {patient_id}: {e}")
            raise VectorServiceError(
                f"Failed to upsert sleep vector: {e}",
                service_name=self.__class__.__name__,
            ) from e

    async def upsert_mood_vector(
        self,
        patient_id: str,
        mood_entry_id: str,
        mood_data: Dict[str, Any],
        patient_age: int,
        patient_gender: str,
    ) -> Dict[str, int]:
        try:
            async with self.qdrant_store.get_client() as client:
                point = self._build_mood_point(
                    patient_id, mood_entry_id, mood_data, patient_age, patient_gender,
                )
                embedding = await embed_text(point["text"])
                if embedding:
                    await client.upsert(
                        collection_name=self.collection_name,
                        points=[PointStruct(
                            id=point["id"], vector=embedding, payload=point["payload"],
                        )],
                    )
                return {"points_created": 1}
        except Exception as e:
            logger.error(f"Failed to upsert mood vector for {patient_id}: {e}")
            raise VectorServiceError(
                f"Failed to upsert mood vector: {e}",
                service_name=self.__class__.__name__,
            ) from e

    def _build_sleep_point(
        self,
        patient_id: str,
        sleep_data: Dict[str, Any],
        patient_age: int,
        patient_gender: str,
    ) -> Dict[str, Any]:
        checkin_date = sleep_data["checkin_date"]
        # Parse checkin_date to datetime for base payload
        if isinstance(checkin_date, str):
            dt = datetime.fromisoformat(checkin_date)
        else:
            dt = datetime.combine(checkin_date, datetime.min.time())

        bed_time_str = sleep_data.get("bed_time", "00:00")
        wake_time_str = sleep_data.get("wake_time", "00:00")

        # Extract hours for numeric filtering
        bed_hour = int(bed_time_str.split(":")[0]) if ":" in bed_time_str else 0
        wake_hour = int(wake_time_str.split(":")[0]) if ":" in wake_time_str else 0

        text_repr = CheckinTextReprBuilder.build_sleep(sleep_data)

        payload = self._build_base_payload(
            patient_id=patient_id,
            patient_age=patient_age,
            patient_gender=patient_gender,
            data_type="sleep_checkin",
            text_repr=text_repr,
            start_time=dt,
            end_time=dt,
            additional_payload={
                "sleep_quality": sleep_data.get("quality"),
                "hours_slept": sleep_data.get("hours_slept"),
                "bed_time_hour": bed_hour,
                "wake_time_hour": wake_hour,
                "has_notes": bool(sleep_data.get("notes")),
            },
        )

        # Deterministic per day — upsert overwrites
        point_id = self._generate_point_id(
            patient_id=patient_id,
            data_type="sleep_checkin",
            start_time=dt,
            end_time=dt,
        )

        return {"id": point_id, "text": text_repr, "payload": payload}

    def _build_mood_point(
        self,
        patient_id: str,
        mood_entry_id: str,
        mood_data: Dict[str, Any],
        patient_age: int,
        patient_gender: str,
    ) -> Dict[str, Any]:
        recorded_at = mood_data.get("recorded_at")
        if isinstance(recorded_at, str):
            dt = datetime.fromisoformat(recorded_at)
        elif isinstance(recorded_at, datetime):
            dt = recorded_at
        else:
            dt = datetime.now().replace(tzinfo=None)

        # Add checkin_date for text builder
        mood_data_with_date = {
            **mood_data,
            "checkin_date": dt.strftime("%Y-%m-%d"),
            "recorded_at": dt.strftime("%H:%M"),
        }

        text_repr = CheckinTextReprBuilder.build_mood(mood_data_with_date)

        payload = self._build_base_payload(
            patient_id=patient_id,
            patient_age=patient_age,
            patient_gender=patient_gender,
            data_type="mood_entry",
            text_repr=text_repr,
            start_time=dt,
            end_time=dt,
            additional_payload={
                "mood_level": mood_data.get("level"),
                "mood_emoji": mood_data.get("emoji"),
                "mood_tags": mood_data.get("tags", []),
                "has_notes": bool(mood_data.get("notes")),
            },
        )

        # Unique per mood entry
        point_id = self._generate_simple_point_id(mood_entry_id)

        return {"id": point_id, "text": text_repr, "payload": payload}

    async def upsert_symptom_vector(
        self,
        patient_id: str,
        symptom_entry_id: str,
        symptom_data: Dict[str, Any],
        patient_age: int,
        patient_gender: str,
    ) -> Dict[str, int]:
        try:
            async with self.qdrant_store.get_client() as client:
                point = self._build_symptom_point(
                    patient_id, symptom_entry_id, symptom_data, patient_age, patient_gender,
                )
                embedding = await embed_text(point["text"])
                if embedding:
                    await client.upsert(
                        collection_name=self.collection_name,
                        points=[PointStruct(
                            id=point["id"], vector=embedding, payload=point["payload"],
                        )],
                    )
                return {"points_created": 1}
        except Exception as e:
            logger.error(f"Failed to upsert symptom vector for {patient_id}: {e}")
            raise VectorServiceError(
                f"Failed to upsert symptom vector: {e}",
                service_name=self.__class__.__name__,
            ) from e

    def _build_symptom_point(
        self,
        patient_id: str,
        symptom_entry_id: str,
        symptom_data: Dict[str, Any],
        patient_age: int,
        patient_gender: str,
    ) -> Dict[str, Any]:
        recorded_at = symptom_data.get("recorded_at")
        if isinstance(recorded_at, str):
            dt = datetime.fromisoformat(recorded_at)
        elif isinstance(recorded_at, datetime):
            dt = recorded_at
        else:
            dt = datetime.now().replace(tzinfo=None)

        # Add checkin_date for text builder
        symptom_data_with_date = {
            **symptom_data,
            "checkin_date": dt.strftime("%Y-%m-%d"),
        }

        symptoms = symptom_data.get("symptoms", [])
        symptom_names = [s.get("symptom_name", "unknown") for s in symptoms]
        severities = [s.get("severity", 1) for s in symptoms]

        text_repr = CheckinTextReprBuilder.build_symptoms(symptom_data_with_date)

        payload = self._build_base_payload(
            patient_id=patient_id,
            patient_age=patient_age,
            patient_gender=patient_gender,
            data_type="symptom_entry",
            text_repr=text_repr,
            start_time=dt,
            end_time=dt,
            additional_payload={
                "symptom_names": symptom_names,
                "symptom_count": len(symptoms),
                "max_severity": max(severities) if severities else 0,
                "avg_severity": round(sum(severities) / len(severities), 1) if severities else 0,
                "has_notes": bool(symptom_data.get("notes")),
            },
        )

        # Unique per symptom entry
        point_id = self._generate_simple_point_id(symptom_entry_id)

        return {"id": point_id, "text": text_repr, "payload": payload}
