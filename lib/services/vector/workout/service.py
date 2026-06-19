"""Workout vector service — embeds manually-logged workout sessions into Qdrant."""

import logging
from datetime import datetime
from typing import Any, Dict

from qdrant_client.http.models import PointStruct

from lib.core.qdrant_store import QdrantStore
from lib.utils.vector_utils import embed_text

from ..base import BaseVectorService
from ..utils.exceptions import VectorServiceError
from .text_builder import WorkoutTextReprBuilder

logger = logging.getLogger(__name__)


class WorkoutVectorService(BaseVectorService):
    """Vectorize patient-logged workouts into Qdrant (data_type='patient_workout')."""

    def __init__(
        self,
        qdrant_store: QdrantStore,
        collection_name: str = "patient_data",
    ):
        super().__init__(qdrant_store, collection_name)

    async def upsert_workout(
        self,
        patient_id: str,
        workout_id: str,
        workout: Dict[str, Any],
        patient_age: int,
        patient_gender: str,
    ) -> Dict[str, int]:
        try:
            async with self.qdrant_store.get_client() as client:
                point = await self._build_point(
                    patient_id, workout_id, workout, patient_age, patient_gender
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
            logger.error(f"❌ Failed to upsert workout {workout_id}: {e}")
            raise VectorServiceError(
                f"Failed to upsert workout: {e}",
                service_name=self.__class__.__name__,
            ) from e

    async def _build_point(
        self,
        patient_id: str,
        workout_id: str,
        workout: Dict[str, Any],
        patient_age: int,
        patient_gender: str,
    ) -> Dict[str, Any]:
        # Combine date + time into a single datetime for bucketing
        date_str = str(workout.get("date"))
        time_str = str(workout.get("time") or "00:00:00")
        try:
            dt = datetime.fromisoformat(f"{date_str}T{time_str}")
        except Exception:
            dt = datetime.fromisoformat(date_str)

        segments = workout.get("segments") or []
        exercises = workout.get("exercises") or []
        if not exercises and segments:
            exercises = [ex for seg in segments for ex in (seg.get("exercises") or [])]

        exercise_ids = [ex.get("exercise_id") for ex in exercises if ex.get("exercise_id")]
        exercise_names = [ex.get("exercise_name") for ex in exercises if ex.get("exercise_name")]
        total_volume_kg = sum(
            (ex.get("sets") or 0) * (ex.get("reps") or 0) * (ex.get("weight_kg") or 0)
            for ex in exercises
        )

        segment_types = sorted({seg.get("type") for seg in segments if seg.get("type")})

        text_repr = WorkoutTextReprBuilder.build(workout)

        payload = self._build_base_payload(
            patient_id=patient_id,
            patient_age=patient_age,
            patient_gender=patient_gender,
            data_type="patient_workout",
            text_repr=text_repr,
            start_time=dt,
            end_time=dt,
            additional_payload={
                "workout_id": workout_id,
                "date": date_str,
                "time": time_str,
                "type": workout.get("type"),
                "duration_minutes": workout.get("duration_minutes"),
                "intensity": workout.get("intensity"),
                "calories_burned": workout.get("calories_burned"),
                "exercise_count": len(exercises),
                "exercise_ids": exercise_ids,
                "exercise_names": exercise_names,
                "total_volume_kg": total_volume_kg if total_volume_kg > 0 else None,
                "fitness_plan_session_id": workout.get("fitness_plan_session_id"),
                "source": workout.get("source", "app"),
                "segment_count": len(segments),
                "segment_types": segment_types,
            },
        )

        point_id = self._generate_simple_point_id(workout_id)
        return {"id": point_id, "text": text_repr, "payload": payload}

    async def delete_workout_vector(self, workout_id: str) -> None:
        try:
            point_id = self._generate_simple_point_id(workout_id)
            await self.delete_points_by_ids([point_id])
            logger.info(f"🗑️ Deleted vector for workout {workout_id}")
        except Exception as e:
            logger.error(f"❌ Failed to delete workout vector {workout_id}: {e}")
            raise VectorServiceError(
                f"Failed to delete workout vector: {e}",
                service_name=self.__class__.__name__,
            ) from e

    async def delete_workout_vectors_for_patient(self, patient_id: str) -> None:
        try:
            await self.delete_points_by_filter(patient_id, data_type="patient_workout")
            logger.info(f"🧹 Deleted all workout vectors for patient {patient_id}")
        except Exception as e:
            logger.error(
                f"❌ Failed to delete workout vectors for patient {patient_id}: {e}"
            )
            raise VectorServiceError(
                f"Failed to delete workout vectors for patient: {e}",
                service_name=self.__class__.__name__,
            ) from e
