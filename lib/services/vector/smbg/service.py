"""SMBG vector service for processing and storing SMBG data."""

import logging
from datetime import datetime
from typing import Dict, Any

from lib.core.qdrant_store import QdrantStore
from qdrant_client.http.models import PointStruct

from ..base import BaseVectorService
from ..utils.exceptions import VectorServiceError
from lib.utils.vector_utils import embed_text
from .text_builder import SMBGTextReprBuilder

logger = logging.getLogger(__name__)


class SMBGVectorService(BaseVectorService):
    """Service for vectorizing SMBG reading data."""

    def __init__(self, qdrant_store: QdrantStore, collection_name: str = "patient_data"):
        """
        Initialize SMBG vector service.

        Args:
            qdrant_store: Qdrant store instance
            collection_name: Collection name for vector storage
        """
        super().__init__(qdrant_store, collection_name)

    async def upsert_smbg(
        self,
        patient_id: str,
        reading_id: str,
        reading: Dict[str, Any],
        patient_age: int,
        patient_gender: str,
    ) -> Dict[str, int]:
        """
        Upsert an SMBG reading to vector store.

        Args:
            patient_id: Patient identifier
            reading_id: Reading identifier
            reading: Reading data dictionary
            patient_age: Patient age
            patient_gender: Patient gender

        Returns:
            Dictionary with points_created count

        Raises:
            VectorServiceError: If upsert fails
        """
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
            raise VectorServiceError(
                f"Failed to upsert SMBG reading: {e}",
                service_name=self.__class__.__name__,
            ) from e

    async def _build_point(
        self,
        patient_id: str,
        reading_id: str,
        reading: Dict[str, Any],
        patient_age: int,
        patient_gender: str,
    ) -> Dict[str, Any]:
        """
        Build point data for an SMBG reading.

        Args:
            patient_id: Patient identifier
            reading_id: Reading identifier
            reading: Reading data dictionary
            patient_age: Patient age
            patient_gender: Patient gender

        Returns:
            Dictionary with id, text, and payload
        """
        dt = datetime.fromisoformat(str(reading["reading_time"]))
        uploaded_at = reading.get("uploaded_at")
        uploaded_at_ms = (
            int(datetime.fromisoformat(str(uploaded_at)).timestamp() * 1000)
            if uploaded_at
            else None
        )

        glucose_mgdl = float(reading.get("glucose_mgdl", 0))
        reading_type = reading.get("type", "").lower()
        notes = reading.get("notes", "")
        source = reading.get("source", "app")

        # Build base payload using base class method
        payload = self._build_base_payload(
            patient_id=patient_id,
            patient_age=patient_age,
            patient_gender=patient_gender,
            data_type="smbg",
            text_repr="",  # Will be set below
            start_time=dt,
            end_time=dt,
            additional_payload={
                "reading_id": reading_id,
                "hour": dt.hour,
                "glucose_mgdl": glucose_mgdl,
                "reading_type": reading_type,
                "reading_time": int(dt.timestamp() * 1000),
                "notes": notes,
                "source": source,
                "uploaded_at": uploaded_at_ms,
            },
        )

        # Build text representation
        text_repr = SMBGTextReprBuilder.build(reading)
        payload["text_repr"] = text_repr

        # Generate point ID
        point_id = self._generate_simple_point_id(reading_id)

        return {
            "id": point_id,
            "text": text_repr,
            "payload": payload,
        }

    async def delete_smbg_vector(self, reading_id: str) -> None:
        """
        Delete an SMBG vector by reading ID.

        Args:
            reading_id: Reading identifier

        Raises:
            VectorServiceError: If deletion fails
        """
        try:
            point_id = self._generate_simple_point_id(reading_id)
            await self.delete_points_by_ids([point_id])
            logger.info(f"🗑️ Deleted vector for SMBG reading {reading_id}")
        except Exception as e:
            logger.error(f"❌ Failed to delete SMBG vector {reading_id}: {e}")
            raise VectorServiceError(
                f"Failed to delete SMBG vector: {e}",
                service_name=self.__class__.__name__,
            ) from e

    async def delete_smbg_vectors_for_patient(self, patient_id: str) -> None:
        """
        Delete all SMBG vectors for a patient.

        Args:
            patient_id: Patient identifier

        Raises:
            VectorServiceError: If deletion fails
        """
        try:
            await self.delete_points_by_filter(patient_id, data_type="smbg")
            logger.info(
                f"🧹 Deleted all SMBG vectors for patient {patient_id}"
            )
        except Exception as e:
            logger.error(
                f"❌ Failed to delete SMBG vectors for patient {patient_id}: {e}"
            )
            raise VectorServiceError(
                f"Failed to delete SMBG vectors for patient: {e}",
                service_name=self.__class__.__name__,
            ) from e
