"""Vector service for diet and fitness plan data."""

import logging
from datetime import datetime
from typing import Any, Dict

from qdrant_client.http.models import PointStruct
from qdrant_client.models import PointIdsList

from lib.core.qdrant_store import QdrantStore
from lib.utils.vector_utils import embed_text

from ..base import BaseVectorService
from ..utils.exceptions import VectorServiceError
from .text_builder import PlansTextReprBuilder

logger = logging.getLogger(__name__)


class PlansVectorService(BaseVectorService):
    """Service for vectorizing diet and fitness plan data."""

    def __init__(self, qdrant_store: QdrantStore, collection_name: str = "patient_data"):
        super().__init__(qdrant_store, collection_name)

    async def upsert_diet_plan_vector(
        self,
        patient_id: str,
        plan_id: str,
        plan_data: Dict[str, Any],
        patient_age: int,
        patient_gender: str,
    ) -> Dict[str, int]:
        try:
            async with self.qdrant_store.get_client() as client:
                point = self._build_diet_plan_point(
                    patient_id, plan_id, plan_data, patient_age, patient_gender,
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
            logger.error(f"Failed to upsert diet plan vector for {patient_id}: {e}")
            raise VectorServiceError(
                f"Failed to upsert diet plan vector: {e}",
                service_name=self.__class__.__name__,
            ) from e

    async def upsert_fitness_plan_vector(
        self,
        patient_id: str,
        plan_id: str,
        plan_data: Dict[str, Any],
        patient_age: int,
        patient_gender: str,
    ) -> Dict[str, int]:
        try:
            async with self.qdrant_store.get_client() as client:
                point = self._build_fitness_plan_point(
                    patient_id, plan_id, plan_data, patient_age, patient_gender,
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
            logger.error(f"Failed to upsert fitness plan vector for {patient_id}: {e}")
            raise VectorServiceError(
                f"Failed to upsert fitness plan vector: {e}",
                service_name=self.__class__.__name__,
            ) from e

    async def delete_plan_vector(self, plan_id: str) -> None:
        try:
            point_id = self._generate_simple_point_id(plan_id)
            async with self.qdrant_store.get_client() as client:
                await client.delete(
                    collection_name=self.collection_name,
                    points_selector=PointIdsList(points=[point_id]),
                )
        except Exception as e:
            logger.error(f"Failed to delete plan vector for {plan_id}: {e}")

    def _build_diet_plan_point(
        self,
        patient_id: str,
        plan_id: str,
        plan_data: Dict[str, Any],
        patient_age: int,
        patient_gender: str,
    ) -> Dict[str, Any]:
        start_date = plan_data.get("start_date")
        end_date = plan_data.get("end_date")

        start_dt = self._parse_date(start_date)
        end_dt = self._parse_date(end_date) if end_date else start_dt

        text_repr = PlansTextReprBuilder.build_diet_plan(plan_data)

        payload = self._build_base_payload(
            patient_id=patient_id,
            patient_age=patient_age,
            patient_gender=patient_gender,
            data_type="diet_plan",
            text_repr=text_repr,
            start_time=start_dt,
            end_time=end_dt,
            additional_payload={
                "calories": plan_data.get("calories"),
                "protein": plan_data.get("protein"),
                "carbs": plan_data.get("carbs"),
                "fats": plan_data.get("fats"),
                "fiber": plan_data.get("fiber"),
                "plan_status": plan_data.get("status", "ACTIVE"),
            },
        )

        point_id = self._generate_simple_point_id(plan_id)
        return {"id": point_id, "text": text_repr, "payload": payload}

    def _build_fitness_plan_point(
        self,
        patient_id: str,
        plan_id: str,
        plan_data: Dict[str, Any],
        patient_age: int,
        patient_gender: str,
    ) -> Dict[str, Any]:
        start_date = plan_data.get("start_date")
        end_date = plan_data.get("end_date")

        start_dt = self._parse_date(start_date)
        end_dt = self._parse_date(end_date) if end_date else start_dt

        text_repr = PlansTextReprBuilder.build_fitness_plan(plan_data)

        content = plan_data.get("content") or {}
        payload = self._build_base_payload(
            patient_id=patient_id,
            patient_age=patient_age,
            patient_gender=patient_gender,
            data_type="fitness_plan",
            text_repr=text_repr,
            start_time=start_dt,
            end_time=end_dt,
            additional_payload={
                "steps_goal": plan_data.get("steps_goal"),
                "sessions_per_week": content.get("sessions_per_week"),
                "weekly_active_minutes": content.get("weekly_active_minutes"),
                "plan_status": plan_data.get("status", "ACTIVE"),
            },
        )

        point_id = self._generate_simple_point_id(plan_id)
        return {"id": point_id, "text": text_repr, "payload": payload}

    @staticmethod
    def _parse_date(d) -> datetime:
        if isinstance(d, str):
            return datetime.fromisoformat(d)
        elif isinstance(d, datetime):
            return d
        elif hasattr(d, "year"):  # date object
            return datetime.combine(d, datetime.min.time())
        return datetime.now().replace(tzinfo=None)
