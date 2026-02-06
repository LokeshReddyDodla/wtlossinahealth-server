"""Patient vitals vector service for processing and storing vitals data."""

import logging
from datetime import datetime
from typing import Dict, Any

from lib.core.qdrant_store import QdrantStore
from qdrant_client.http.models import PointStruct

from ..base import BaseVectorService
from ..utils.exceptions import VectorServiceError
from lib.utils.vector_utils import embed_text
from .text_builder import VitalsTextReprBuilder

logger = logging.getLogger(__name__)


class VitalsVectorService(BaseVectorService):
    """Service for vectorizing patient vitals data."""

    def __init__(
        self, qdrant_store: QdrantStore, collection_name: str = "patient_data"
    ):
        """
        Initialize Vitals vector service.

        Args:
            qdrant_store: Qdrant store instance
            collection_name: Collection name for vector storage
        """
        super().__init__(qdrant_store, collection_name)

    async def upsert_vital(
        self,
        patient_id: str,
        vital_id: str,
        vital: Dict[str, Any],
        patient_age: int,
        patient_gender: str,
    ) -> Dict[str, int]:
        """
        Upsert a vital reading to vector store.

        Args:
            patient_id: Patient identifier
            vital_id: Vital reading identifier
            vital: Vital data dictionary
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
                    patient_id, vital_id, vital, patient_age, patient_gender
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
            logger.error(
                f"❌ Failed to upsert vital {vital_id} for patient {patient_id}: {e}"
            )
            raise VectorServiceError(
                f"Failed to upsert vital: {e}",
                service_name=self.__class__.__name__,
            ) from e

    async def _build_point(
        self,
        patient_id: str,
        vital_id: str,
        vital: Dict[str, Any],
        patient_age: int,
        patient_gender: str,
    ) -> Dict[str, Any]:
        """
        Build point data for a vital reading.

        Args:
            patient_id: Patient identifier
            vital_id: Vital reading identifier
            vital: Vital data dictionary
            patient_age: Patient age
            patient_gender: Patient gender

        Returns:
            Dictionary with id, text, and payload
        """
        # Parse test time
        test_time = vital.get("test_time")
        if isinstance(test_time, str):
            dt = datetime.fromisoformat(test_time.replace("Z", "+00:00"))
        elif isinstance(test_time, datetime):
            dt = test_time
        else:
            raise ValueError(f"Invalid test_time format: {test_time}")

        uploaded_at = vital.get("uploaded_at")
        uploaded_at_ms = None
        if uploaded_at:
            if isinstance(uploaded_at, str):
                uploaded_at_dt = datetime.fromisoformat(
                    str(uploaded_at).replace("Z", "+00:00")
                )
            else:
                uploaded_at_dt = uploaded_at
            uploaded_at_ms = int(uploaded_at_dt.timestamp() * 1000)

        # Build base payload using base class method
        payload = self._build_base_payload(
            patient_id=patient_id,
            patient_age=patient_age,
            patient_gender=patient_gender,
            data_type="vital",
            text_repr="",  # Will be set below
            start_time=dt,
            end_time=dt,
            additional_payload={
                "vital_id": vital_id,
                "hour": dt.hour,
                "a1c": vital.get("a1c"),
                "creatinine": vital.get("creatinine"),
                "diastolic_bp": vital.get("diastolic_bp"),
                "systolic_bp": vital.get("systolic_bp"),
                "heart_rate": vital.get("heart_rate"),
                "ketones": vital.get("ketones"),
                "respiratory_rate": vital.get("respiratory_rate"),
                "spo2": vital.get("spo2"),
                "temperature": vital.get("temperature"),
                "weight": vital.get("weight"),
                "test_time": int(dt.timestamp() * 1000),
                "source_name": vital.get("source_name", ""),
                "source_platform": vital.get("source_platform", ""),
                "uploaded_at": uploaded_at_ms,
            },
        )

        # Build text representation
        text_repr = VitalsTextReprBuilder.build(vital)
        payload["text_repr"] = text_repr

        # Generate point ID
        point_id = self._generate_simple_point_id(vital_id)

        return {
            "id": point_id,
            "text": text_repr,
            "payload": payload,
        }

    async def delete_vital_vector(self, vital_id: str) -> None:
        """
        Delete a vital vector by vital ID.

        Args:
            vital_id: Vital identifier

        Raises:
            VectorServiceError: If deletion fails
        """
        try:
            point_id = self._generate_simple_point_id(vital_id)
            await self.delete_points_by_ids([point_id])
            logger.info(f"🗑️ Deleted vector for vital {vital_id}")
        except Exception as e:
            logger.error(f"❌ Failed to delete vital vector {vital_id}: {e}")
            raise VectorServiceError(
                f"Failed to delete vital vector: {e}",
                service_name=self.__class__.__name__,
            ) from e

    async def delete_vital_vectors_for_patient(self, patient_id: str) -> None:
        """
        Delete all vital vectors for a patient.

        Args:
            patient_id: Patient identifier

        Raises:
            VectorServiceError: If deletion fails
        """
        try:
            await self.delete_points_by_filter(patient_id, data_type="vital")
            logger.info(
                f"🧹 Deleted all vital vectors for patient {patient_id}"
            )
        except Exception as e:
            logger.error(
                f"❌ Failed to delete vital vectors for patient {patient_id}: {e}"
            )
            raise VectorServiceError(
                f"Failed to delete vital vectors for patient: {e}",
                service_name=self.__class__.__name__,
            ) from e
