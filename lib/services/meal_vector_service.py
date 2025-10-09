import hashlib
from datetime import datetime
import logging
from typing import Dict, List, Any
from qdrant_client.http.models import PointStruct
from openai import AsyncOpenAI
from lib.core.qdrant_store import QdrantStore

logger = logging.getLogger(__name__)
import hashlib
import logging
from datetime import datetime
from typing import Dict, Any

from qdrant_client.http.models import PointStruct
from openai import AsyncOpenAI

from lib.core.qdrant_store import QdrantStore
from lib.utils.vector_utils import embed_text

logger = logging.getLogger(__name__)


class MealVectorService:
    def __init__(
        self,
        qdrant_store: QdrantStore,
        collection_name: str = "patient_data",
    ):
        self.qdrant_store = qdrant_store
        self.collection_name = collection_name
        self.openai_client = AsyncOpenAI()

    async def upsert_meal(
        self,
        patient_id: str,
        meal_id: str,
        meal: Dict[str, Any],
        patient_age: int,
        patient_gender: str,
    ):
        try:
            async with self.qdrant_store.get_client() as client:
                point = await self._build_point(
                    patient_id, meal_id, meal, patient_age, patient_gender
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
                f"❌ Failed to upsert meal {meal_id} for patient {patient_id}: {e}"
            )
            raise

    def _generate_point_id(self, meal_id: str) -> str:
        return hashlib.md5(meal_id.encode()).hexdigest()

    async def _build_point(
        self,
        patient_id: str,
        meal_id: str,
        meal: Dict[str, Any],
        patient_age: int,
        patient_gender: str,
    ) -> Dict[str, Any]:
        dt = datetime.fromisoformat(f"{meal.get('date')}T{meal.get('time')}")
        uploaded_at_ms = int(meal.get("uploaded_at").timestamp() * 1000)  # type: ignore

        base_meta = {
            "patient_id": patient_id,
            "patient_age": patient_age,
            "patient_gender": patient_gender,
            "meal_id": meal_id,
            "data_type": "meal",
            "source": "meal",
            "start_time": int(dt.timestamp() * 1000),
            "end_time": int(dt.timestamp() * 1000),
            "date": meal.get("date"),
            "day_of_week": dt.weekday(),
            "is_weekend": dt.weekday() >= 5,
            "week_number": dt.isocalendar()[1],
            "month": dt.month,
            "time_of_day_bucket": [self._bucket_time(dt.hour)],
            "meal_name": meal.get("name"),
            "meal_type": meal.get("type"),
            "meal_date": meal.get("date"),
            "meal_time": meal.get("time"),
            "image_url": meal.get("image_url"),
            "description": meal.get("description"),
            "analyzed": meal.get("analyzed"),
            "tags": meal.get("tags", []),
            "uploaded_at": uploaded_at_ms,
        }

        macros = meal.get("total_macro_nutritional_value", {})
        micros = meal.get("total_micro_nutritional_value", {})

        base_meta.update({"nutrition": {**macros, **micros}})

        # Add each food item to payload
        items = []
        for item in meal.get("items", []):
            items.append(
                {
                    "item_name": item.get("name"),
                    "serving_quantity": item.get("serving_quantity"),
                    "serving_unit": item.get("serving_unit"),
                    "serving_size": item.get("serving_size"),
                    "macro_nutritional_values": item.get(
                        "macro_nutritional_values", {}
                    ),
                    "micro_nutritional_values": item.get(
                        "micro_nutritional_values", {}
                    ),
                }
            )
        base_meta["items"] = items

        # Combine text for embedding
        text_parts = [
            f"Meal Name: {meal.get('name', '')} ({meal.get('type', '')})",
            f"Description: {meal.get('description', '')}",
            f"Tags: {', '.join(meal.get('tags', []))}",
            f"Date & Time: {meal.get('date', '')} {meal.get('time', '')}",
            f"Analyzed: {meal.get('analyzed', False)}",
            f"Image URL: {meal.get('image_url', '')}",
            "Nutrition Summary: "
            + ", ".join(
                [f"{k}: {v}" for k, v in {**macros, **micros}.items()]
            ),
        ]

        for idx, item in enumerate(items, start=1):
            text_parts.append(
                f"Food Item {idx}: {item.get('item_name', '')}. "
                f"Serving: {item.get('serving_quantity', '')} {item.get('serving_unit', '')} "
                f"({item.get('serving_size', '')}). "
                "Macro Nutrition: "
                + ", ".join(
                    [
                        f"{k}: {v}"
                        for k, v in item.get(
                            "macro_nutritional_values", {}
                        ).items()
                    ]
                )
                + ". Micro Nutrition: "
                + ", ".join(
                    [
                        f"{k}: {v}"
                        for k, v in item.get(
                            "micro_nutritional_values", {}
                        ).items()
                    ]
                )
            )
        combined_text = "\n".join(filter(None, text_parts))
        return {
            "id": self._generate_point_id(meal_id),
            "text": combined_text,
            "payload": base_meta,
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
