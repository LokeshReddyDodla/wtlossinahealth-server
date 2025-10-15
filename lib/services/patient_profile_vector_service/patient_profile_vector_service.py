import hashlib
import logging
from typing import Dict, Any
from openai import AsyncOpenAI

from qdrant_client.http.models import (
    PointStruct,
    PointIdsList,
)

from lib.services.patient_profile_vector_service.patient_profile_text_repr_builder import (
    PatientProfileTextReprBuilder,
)
from lib.utils.vector_utils import embed_text

logger = logging.getLogger(__name__)


class PatientProfileVectorService:
    def __init__(self, qdrant_store, collection_name: str = "patient_data"):
        self.qdrant_store = qdrant_store
        self.collection_name = collection_name
        self.openai_client = AsyncOpenAI()

    async def upsert_profile(
        self,
        profile_data: Dict[str, Any],
    ):
        try:
            async with self.qdrant_store.get_client() as client:
                point = await self._build_point(profile_data)

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
                f"❌ Failed to upsert patient profile {profile_data['patient_id']}: {e}"
            )
            raise

    def _generate_point_id(self, reading_id: str) -> str:
        return hashlib.md5(reading_id.encode()).hexdigest()

    async def _build_point(
        self,
        profile_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        patient_id = profile_data.get("patient_id")
        first_name = profile_data.get("first_name", "")
        last_name = profile_data.get("last_name", "")
        age = profile_data.get("age")
        gender = profile_data.get("gender")
        height = profile_data.get("height")
        weight = profile_data.get("weight")
        waist = profile_data.get("waist")
        bmi = (
            round(weight / (height / 100) ** 2, 1)
            if height and weight
            else None
        )

        # Daily activity
        activity_level = profile_data.get("daily_activity", {}).get(
            "activity_level"
        )

        # Allergies
        food_allergies = [
            a.get("allergy_name")
            for a in profile_data.get("food_allergies", [])
        ]
        drug_allergies = [
            a.get("allergy_name")
            for a in profile_data.get("drug_allergies", [])
        ]

        # Alcohol
        alcohol = profile_data.get("alcohol_consumption", {})
        alcohol_consumption = alcohol.get("consume_alcohol", False)
        alcohol_frequency = alcohol.get("frequency", "")
        alcohol_quantity = alcohol.get("quantity", "")
        alcohol_types = alcohol.get("type_of_alcohol", [])

        # Smoking
        smoking = profile_data.get("smoking_habit", {})
        smoking_habit = smoking.get("smoke_status", False)
        years_of_smoking = smoking.get("years_of_smoking", 0)
        cigarettes_per_day = smoking.get("cigarettes_per_day", 0)
        quit_years_ago = smoking.get("quit_years_ago", 0)

        # Eating habits
        eating = profile_data.get("eating_habit", {})
        snacks_count = eating.get("snacks_count", 0)
        meals_per_day = eating.get("meals_per_day", 0)
        meal_timings = [
            m.get("meal_type") for m in eating.get("meal_timings", [])
        ]
        cuisine_preferences = eating.get("cuisine_preferences", [])
        diet_preference = eating.get("diet_preferences", {}).get(
            "preference", ""
        )

        # Sleep
        sleep = profile_data.get("sleep_habit", {})
        sleep_quality = sleep.get("sleep_quality", "")
        wake_up_fresh = sleep.get("wake_up_fresh", False)
        drowsy_day = sleep.get("drowsy_day", False)
        average_sleep_duration = sleep.get("average_sleep_duration", "")
        wake_up_time = sleep.get("wake_up_time", "")
        bed_time = sleep.get("bed_time", "")

        # Diabetes history
        diabetic = profile_data.get("diabetic_history", {})
        type_of_diabetes = diabetic.get("type_of_diabetes", "")
        years_with_diabetes = diabetic.get("years_with_diabetes", 0)
        is_pregnant = diabetic.get("is_pregnant", False)
        pregnancy_weeks = diabetic.get("pregnancy_weeks", 0)

        # Family history
        family_histories = profile_data.get("family_diabetic_histories", [])
        family_diabetic_members = [
            f.get("family_member") for f in family_histories
        ]
        family_diabetic_years = [
            f.get("years_with_diabetes") for f in family_histories
        ]

        # Medical histories
        medical_histories = profile_data.get("medical_histories", [])
        medical_conditions = [m.get("condition") for m in medical_histories]
        medical_conditions_years = [
            m.get("duration_years") for m in medical_histories
        ]
        medical_conditions_details = [
            m.get("details") for m in medical_histories
        ]

        # TODO: Current medication

        payload = {
            "data_type": "profile",
            "patient_id": str(patient_id),
            "first_name": first_name,
            "last_name": last_name,
            "age": age,
            "gender": gender,
            "height": height,
            "weight": weight,
            "waist": waist,
            "bmi": bmi,
            "activity_level": activity_level,
            "food_allergies": food_allergies,
            "drug_allergies": drug_allergies,
            "alcohol_consumption": alcohol_consumption,
            "alcohol_consumption_frequency": alcohol_frequency,
            "alcohol_consumption_quantity": alcohol_quantity,
            "alcohol_consumption_types": alcohol_types,
            "smoking_habit": smoking_habit,
            "years_of_smoking": years_of_smoking,
            "cigarettes_per_day": cigarettes_per_day,
            "quit_years_ago": quit_years_ago,
            "snacks_count": snacks_count,
            "meals_per_day": meals_per_day,
            "meal_timings": meal_timings,
            "cuisine_preferences": cuisine_preferences,
            "diet_preference": diet_preference,
            "sleep_quality": sleep_quality,
            "wake_up_fresh": wake_up_fresh,
            "drowsy_day": drowsy_day,
            "average_sleep_duration": average_sleep_duration,
            "wake_up_time": wake_up_time,
            "bed_time": bed_time,
            "type_of_diabetes": type_of_diabetes,
            "years_with_diabetes": years_with_diabetes,
            "is_pregnant": is_pregnant,
            "pregnancy_weeks": pregnancy_weeks,
            "family_diabetic_members": family_diabetic_members,
            "family_diabetic_years": family_diabetic_years,
            "medical_conditions": medical_conditions,
            "medical_conditions_years": medical_conditions_years,
            "medical_conditions_details": medical_conditions_details,
        }

        # Build text representation for embedding
        text_repr = PatientProfileTextReprBuilder.build(profile_data)
        payload["text_repr"] = text_repr

        return {
            "id": self._generate_point_id(str(patient_id)),
            "text": text_repr,
            "payload": payload,
        }

    async def delete_profile_vector(self, patient_id: str):
        try:
            point_id = self._generate_point_id(patient_id)
            async with self.qdrant_store.get_client() as client:
                await client.delete(
                    collection_name=self.collection_name,
                    points_selector=PointIdsList(points=[point_id]),
                )
            logger.info(f"🗑️ Deleted profile vector for patient {patient_id}")
        except Exception as e:
            logger.error(
                f"❌ Failed to delete profile vector for patient {patient_id}: {e}"
            )
