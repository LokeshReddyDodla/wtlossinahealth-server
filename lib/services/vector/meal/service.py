"""Meal vector service for processing and storing meal data."""

import logging
from datetime import datetime
from typing import Dict, Any

from lib.core.qdrant_store import QdrantStore
from qdrant_client.http.models import PointIdsList, PointStruct

from ..base import BaseVectorService
from ..utils.exceptions import VectorServiceError
from lib.utils.vector_utils import embed_text
from .text_builder import MealTextReprBuilder

logger = logging.getLogger(__name__)


class MealVectorService(BaseVectorService):
    """Service for vectorizing meal data."""

    def __init__(
        self,
        qdrant_store: QdrantStore,
        collection_name: str = "patient_data",
    ):
        """
        Initialize Meal vector service.

        Args:
            qdrant_store: Qdrant store instance
            collection_name: Collection name for vector storage
        """
        super().__init__(qdrant_store, collection_name)

    async def upsert_meal(
        self,
        patient_id: str,
        meal_id: str,
        meal: Dict[str, Any],
        patient_age: int,
        patient_gender: str,
    ) -> Dict[str, int]:
        """
        Upsert a meal to vector store.

        Args:
            patient_id: Patient identifier
            meal_id: Meal identifier
            meal: Meal data dictionary
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
                    patient_id, meal_id, meal, patient_age, patient_gender
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
            logger.error(
                f"❌ Failed to upsert meal {meal_id} for patient {patient_id}: {e}"
            )
            raise VectorServiceError(
                f"Failed to upsert meal: {e}",
                service_name=self.__class__.__name__,
            ) from e

    async def _build_point(
        self,
        patient_id: str,
        meal_id: str,
        meal: Dict[str, Any],
        patient_age: int,
        patient_gender: str,
    ) -> Dict[str, Any]:
        """
        Build point data for a meal.

        Args:
            patient_id: Patient identifier
            meal_id: Meal identifier
            meal: Meal data dictionary
            patient_age: Patient age
            patient_gender: Patient gender

        Returns:
            Dictionary with id, text, and payload
        """
        dt = datetime.fromisoformat(f"{meal.get('date')}T{meal.get('time')}")
        uploaded_at = meal.get("uploaded_at")
        uploaded_at_ms = (
            int(datetime.fromisoformat(str(uploaded_at)).timestamp() * 1000)
            if uploaded_at
            else None
        )

        # Build base payload using base class method
        payload = self._build_base_payload(
            patient_id=patient_id,
            patient_age=patient_age,
            patient_gender=patient_gender,
            data_type="meal",
            text_repr="",  # Will be set below
            start_time=dt,
            end_time=dt,
            additional_payload={
                "meal_id": meal_id,
                "meal_name": meal.get("name"),
                "meal_type": meal.get("type"),
                "meal_date": meal.get("date"),
                "meal_time": meal.get("time"),
                "image_url": meal.get("image_url"),
                "image_urls": meal.get("image_urls"),
                "description": meal.get("description"),
                "note": meal.get("note"),
                "analyzed": meal.get("analyzed"),
                "tags": meal.get("tags", []),
                "uploaded_at": uploaded_at_ms,
            },
        )

        # Add nutrition data
        macros = meal.get("total_macro_nutritional_value") or {}
        micros = meal.get("total_micro_nutritional_value") or {}
        payload["nutrition"] = {**macros, **micros}

        # Add food items
        items = []
        for item in meal.get("items") or []:
            items.append(
                {
                    "item_name": item.get("name"),
                    "serving_quantity": item.get("serving_quantity"),
                    "serving_unit": item.get("serving_unit"),
                    "serving_size": item.get("serving_size"),
                    "macro_nutritional_values": item.get("macro_nutritional_values") or {},
                    "micro_nutritional_values": item.get("micro_nutritional_values") or {},
                }
            )
        payload["items"] = items

        # Build text representation
        combined_text = MealTextReprBuilder.build(meal)
        payload["text_repr"] = combined_text

        # Generate point ID
        point_id = self._generate_simple_point_id(meal_id)

        return {
            "id": point_id,
            "text": combined_text,
            "payload": payload,
        }

    async def delete_meal_vector(self, meal_id: str) -> None:
        """
        Delete a meal vector by meal ID.

        Args:
            meal_id: Meal identifier

        Raises:
            VectorServiceError: If deletion fails
        """
        try:
            point_id = self._generate_simple_point_id(meal_id)
            await self.delete_points_by_ids([point_id])
            logger.info(f"🗑️ Deleted vector for meal {meal_id}")
        except Exception as e:
            logger.error(f"❌ Failed to delete meal vector {meal_id}: {e}")
            raise VectorServiceError(
                f"Failed to delete meal vector: {e}",
                service_name=self.__class__.__name__,
            ) from e

    async def delete_meal_vectors_for_patient(self, patient_id: str) -> None:
        """
        Delete all meal vectors for a patient.

        Args:
            patient_id: Patient identifier

        Raises:
            VectorServiceError: If deletion fails
        """
        try:
            await self.delete_points_by_filter(patient_id, data_type="meal")
            logger.info(
                f"🧹 Deleted all meal vectors for patient {patient_id}"
            )
        except Exception as e:
            logger.error(
                f"❌ Failed to delete meal vectors for patient {patient_id}: {e}"
            )
            raise VectorServiceError(
                f"Failed to delete meal vectors for patient: {e}",
                service_name=self.__class__.__name__,
            ) from e
