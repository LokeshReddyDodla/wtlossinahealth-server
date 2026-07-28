"""InBody vector service — one point per body-composition report."""

import logging
from datetime import date, datetime, time
from typing import Any, Dict, Optional

from qdrant_client.http.models import PointStruct

from lib.core.qdrant_store import QdrantStore
from lib.utils.vector_utils import embed_text

from ..base import BaseVectorService
from ..utils.constants import DATA_TYPE_INBODY
from ..utils.exceptions import VectorServiceError
from .text_builder import InbodyTextReprBuilder

logger = logging.getLogger(__name__)

# Canonical measurement names copied flat into the payload so the retrieval
# layer can filter/inspect values without parsing the text_repr.
_PAYLOAD_MEASUREMENTS = (
    "weight",
    "skeletal_muscle_mass",
    "body_fat_mass",
    "percent_body_fat",
    "bmi",
    "basal_metabolic_rate",
    "visceral_fat_level",
    "total_body_water",
    "ecw_ratio",
    "waist_hip_ratio",
    "phase_angle",
    "smi",
)


class InbodyVectorService(BaseVectorService):
    """Service for vectorizing InBody body-composition reports."""

    def __init__(
        self, qdrant_store: QdrantStore, collection_name: str = "patient_data"
    ):
        super().__init__(qdrant_store, collection_name)

    async def upsert_report(
        self,
        patient_id: str,
        report_id: str,
        report_date: date,
        analysis: Dict[str, Any],
        patient_age: int,
        patient_gender: str,
        needs_review: bool = False,
    ) -> Dict[str, int]:
        """
        Upsert one InBody report to the vector store.

        The point id derives from report_id alone, so re-extraction of the
        same report overwrites its point in place.
        """
        try:
            point = await self._build_point(
                patient_id=patient_id,
                report_id=report_id,
                report_date=report_date,
                analysis=analysis,
                patient_age=patient_age,
                patient_gender=patient_gender,
                needs_review=needs_review,
            )

            embedding = await embed_text(point["text"])
            if embedding:
                async with self.qdrant_store.get_client() as client:
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
                f"❌ Failed to upsert InBody report {report_id} "
                f"for patient {patient_id}: {e}"
            )
            raise VectorServiceError(
                f"Failed to upsert InBody report: {e}",
                service_name=self.__class__.__name__,
            ) from e

    async def _build_point(
        self,
        *,
        patient_id: str,
        report_id: str,
        report_date: date,
        analysis: Dict[str, Any],
        patient_age: int,
        patient_gender: str,
        needs_review: bool,
    ) -> Dict[str, Any]:
        # A scan is a point-in-time snapshot; anchor it to midday so naive
        # date-range filters on either side of the day still include it.
        dt = datetime.combine(report_date, time(hour=12))

        additional_payload: Dict[str, Any] = {
            "report_id": report_id,
            "report_date": report_date.isoformat(),
            "inbody_score": analysis.get("inbody_score"),
            "needs_review": needs_review,
        }
        additional_payload.update(
            self._extract_measurement_fields(analysis)
        )

        text_repr = InbodyTextReprBuilder.build(
            analysis=analysis,
            report_date=report_date.isoformat(),
            needs_review=needs_review,
        )

        payload = self._build_base_payload(
            patient_id=patient_id,
            patient_age=patient_age,
            patient_gender=patient_gender,
            data_type=DATA_TYPE_INBODY,
            text_repr=text_repr,
            start_time=dt,
            end_time=dt,
            additional_payload=additional_payload,
        )

        return {
            "id": self._generate_simple_point_id(report_id),
            "text": text_repr,
            "payload": payload,
        }

    @staticmethod
    def _extract_measurement_fields(
        analysis: Dict[str, Any]
    ) -> Dict[str, Optional[float]]:
        by_name = {
            m.get("name"): m.get("value")
            for m in analysis.get("measurements") or []
            if m.get("name")
        }
        return {
            name: by_name.get(name) for name in _PAYLOAD_MEASUREMENTS
        }

    async def delete_report_vector(self, report_id: str) -> None:
        """Delete one InBody report vector by report ID."""
        try:
            point_id = self._generate_simple_point_id(report_id)
            await self.delete_points_by_ids([point_id])
            logger.info(f"🗑️ Deleted vector for InBody report {report_id}")
        except Exception as e:
            logger.error(
                f"❌ Failed to delete InBody report vector {report_id}: {e}"
            )
            raise VectorServiceError(
                f"Failed to delete InBody report vector: {e}",
                service_name=self.__class__.__name__,
            ) from e

    async def delete_report_vectors_for_patient(
        self, patient_id: str
    ) -> None:
        """Delete all InBody report vectors for a patient."""
        try:
            await self.delete_points_by_filter(
                patient_id, data_type=DATA_TYPE_INBODY
            )
            logger.info(
                f"🧹 Deleted all InBody vectors for patient {patient_id}"
            )
        except Exception as e:
            logger.error(
                f"❌ Failed to delete InBody vectors for patient "
                f"{patient_id}: {e}"
            )
            raise VectorServiceError(
                f"Failed to delete InBody vectors for patient: {e}",
                service_name=self.__class__.__name__,
            ) from e
