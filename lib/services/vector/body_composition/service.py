"""Body-composition vector service — one point per confirmed scan."""

import logging
from datetime import datetime
from typing import Any, Dict

from qdrant_client.http.models import PointStruct

from lib.core.qdrant_store import QdrantStore
from lib.services.body_composition.metrics import SPEC_BY_KEY
from lib.utils.vector_utils import embed_text

from ..base import BaseVectorService
from ..utils.constants import DATA_TYPE_BODY_COMPOSITION
from ..utils.exceptions import VectorServiceError
from .text_builder import BodyCompositionTextReprBuilder

logger = logging.getLogger(__name__)


class BodyCompositionVectorService(BaseVectorService):
    """Vectorizes device-neutral body-composition scans for retrieval."""

    def __init__(self, qdrant_store: QdrantStore, collection_name: str = "patient_data"):
        super().__init__(qdrant_store, collection_name)

    async def upsert_record(
        self,
        patient_id: str,
        record_id: str,
        record: Dict[str, Any],
        patient_age: int,
        patient_gender: str,
    ) -> Dict[str, int]:
        try:
            point = self._build_point(
                patient_id, record_id, record, patient_age, patient_gender
            )
            embedding = await embed_text(point["text"])
            if embedding:
                await self.qdrant_store.upsert_points(
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
            logger.error(f"❌ Failed to upsert body-composition {record_id}: {e}")
            raise VectorServiceError(
                f"Failed to upsert body-composition scan: {e}",
                service_name=self.__class__.__name__,
            ) from e

    def _build_point(
        self,
        patient_id: str,
        record_id: str,
        record: Dict[str, Any],
        patient_age: int,
        patient_gender: str,
    ) -> Dict[str, Any]:
        raw_dt = record.get("test_datetime") or record.get("created_at")
        try:
            dt = datetime.fromisoformat(str(raw_dt))
        except (TypeError, ValueError):
            dt = datetime.now()

        metrics = record.get("metrics") or {}
        # Flat measurement columns so retrieval can filter/inspect without
        # parsing the text — same convention the other domains use.
        flat = {
            SPEC_BY_KEY[k].column: v
            for k, v in metrics.items()
            if k in SPEC_BY_KEY
        }

        text_repr = BodyCompositionTextReprBuilder.build(record)
        payload = self._build_base_payload(
            patient_id=patient_id,
            patient_age=patient_age,
            patient_gender=patient_gender,
            data_type=DATA_TYPE_BODY_COMPOSITION,
            text_repr=text_repr,
            start_time=dt,
            end_time=dt,
            additional_payload={
                "record_id": record_id,
                "manufacturer": record.get("manufacturer"),
                "device_model": record.get("device_model"),
                "measurement_method": record.get("measurement_method"),
                **flat,
            },
        )

        return {
            "id": self._generate_simple_point_id(record_id),
            "text": text_repr,
            "payload": payload,
        }

    async def delete_record_vector(self, record_id: str) -> None:
        try:
            await self.delete_points_by_ids(
                [self._generate_simple_point_id(record_id)]
            )
            logger.info(f"🗑️ Deleted body-composition vector {record_id}")
        except Exception as e:
            logger.error(f"❌ Failed to delete body-composition vector {record_id}: {e}")
            raise VectorServiceError(
                f"Failed to delete body-composition vector: {e}",
                service_name=self.__class__.__name__,
            ) from e
