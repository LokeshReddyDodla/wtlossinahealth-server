"""Patient profile vector service for processing and storing profile data."""

import logging
from typing import Dict, Any

from lib.core.qdrant_store import QdrantStore
from qdrant_client.http.models import PointIdsList, PointStruct

from ..base import BaseVectorService
from ..utils.exceptions import VectorServiceError
from lib.utils.vector_utils import embed_text
from .text_builder import PatientProfileTextReprBuilder

logger = logging.getLogger(__name__)


class PatientProfileVectorService(BaseVectorService):
    """Service for vectorizing patient profile data."""

    def __init__(self, qdrant_store: QdrantStore, collection_name: str = "patient_data"):
        """
        Initialize Patient Profile vector service.

        Args:
            qdrant_store: Qdrant store instance
            collection_name: Collection name for vector storage
        """
        super().__init__(qdrant_store, collection_name)

    async def upsert_profile(
        self,
        profile_data: Dict[str, Any],
    ) -> Dict[str, int]:
        """
        Upsert a patient profile to vector store.

        Args:
            profile_data: Patient profile data dictionary

        Returns:
            Dictionary with points_created count

        Raises:
            VectorServiceError: If upsert fails
        """
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
            patient_id = profile_data.get("patient_id", "unknown")
            logger.error(
                f"❌ Failed to upsert patient profile {patient_id}: {e}"
            )
            raise VectorServiceError(
                f"Failed to upsert patient profile: {e}",
                service_name=self.__class__.__name__,
            ) from e

    async def _build_point(
        self,
        profile_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Build point data for a patient profile.

        Args:
            profile_data: Patient profile data dictionary

        Returns:
            Dictionary with id, text, and payload
        """
        profile_data = profile_data or {}

        def safe_dict(value):
            return value if isinstance(value, dict) else {}

        def safe_list(value):
            return value if isinstance(value, list) else []

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
        daily_activity = safe_dict(profile_data.get("daily_activity"))
        activity_level = daily_activity.get("activity_level")

        # Allergies
        food_allergies = safe_list(profile_data.get("food_allergies"))
        drug_allergies = safe_list(profile_data.get("drug_allergies"))

        food_allergies = [a.get("allergy_name") for a in food_allergies]
        drug_allergies = [a.get("allergy_name") for a in drug_allergies]

        # Alcohol
        alcohol = safe_dict(profile_data.get("alcohol_consumption"))
        alcohol_consumption = alcohol.get("consume_alcohol", False)
        alcohol_frequency = alcohol.get("frequency", "")
        alcohol_quantity = alcohol.get("quantity", "")
        alcohol_types = alcohol.get("type_of_alcohol", [])
        if isinstance(alcohol_types, str):
            alcohol_types = [alcohol_types]

        # Smoking
        smoking = safe_dict(profile_data.get("smoking_habit"))
        smoking_habit = smoking.get("smoke_status", False)
        years_of_smoking = smoking.get("years_of_smoking", 0)
        cigarettes_per_day = smoking.get("cigarettes_per_day", 0)
        quit_years_ago = smoking.get("quit_years_ago", 0)

        # Eating habits
        eating = safe_dict(profile_data.get("eating_habit"))
        snacks_count = eating.get("snacks_count", 0)
        meals_per_day = eating.get("meals_per_day", 0)
        meal_timings = [
            m.get("meal_type") for m in safe_list(eating.get("meal_timings"))
        ]
        cuisine_preferences = safe_list(eating.get("cuisine_preferences"))
        diet_preference = ""
        diet_pref_value = eating.get("diet_preferences")
        if isinstance(diet_pref_value, dict):
            diet_preference = diet_pref_value.get("preference", "")

        # Sleep
        sleep = safe_dict(profile_data.get("sleep_habit"))
        sleep_quality = sleep.get("sleep_quality", "")
        wake_up_fresh = sleep.get("wake_up_fresh", False)
        drowsy_day = sleep.get("drowsy_day", False)
        average_sleep_duration = sleep.get("average_sleep_duration", "")
        wake_up_time = sleep.get("wake_up_time", "")
        bed_time = sleep.get("bed_time", "")

        # Diabetes history
        diabetic = safe_dict(profile_data.get("diabetic_history"))
        type_of_diabetes = diabetic.get("type_of_diabetes", "")
        years_with_diabetes = diabetic.get("years_with_diabetes", 0)
        is_pregnant = diabetic.get("is_pregnant", False)
        pregnancy_weeks = diabetic.get("pregnancy_weeks", 0)

        # Family history
        family_histories = safe_list(
            profile_data.get("family_diabetic_histories")
        )
        family_diabetic_members = [
            f.get("family_member") for f in family_histories
        ]
        family_diabetic_years = [
            f.get("years_with_diabetes") for f in family_histories
        ]

        # Medical histories
        medical_histories = safe_list(profile_data.get("medical_histories"))
        medical_conditions = [m.get("condition") for m in medical_histories]
        medical_conditions_years = [
            m.get("duration_years") for m in medical_histories
        ]
        medical_conditions_details = [
            m.get("details") for m in medical_histories
        ]

        # Build payload (profile doesn't have time-based data)
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

        # Build text representation
        text_repr = PatientProfileTextReprBuilder.build(profile_data)
        payload["text_repr"] = text_repr

        # Generate point ID
        point_id = self._generate_simple_point_id(str(patient_id))

        return {
            "id": point_id,
            "text": text_repr,
            "payload": payload,
        }

    async def delete_profile_vector(self, patient_id: str) -> None:
        """
        Delete a profile vector by patient ID.

        Args:
            patient_id: Patient identifier

        Raises:
            VectorServiceError: If deletion fails
        """
        try:
            point_id = self._generate_simple_point_id(patient_id)
            await self.delete_points_by_ids([point_id])
            logger.info(f"🗑️ Deleted profile vector for patient {patient_id}")
        except Exception as e:
            logger.error(
                f"❌ Failed to delete profile vector for patient {patient_id}: {e}"
            )
            raise VectorServiceError(
                f"Failed to delete profile vector: {e}",
                service_name=self.__class__.__name__,
            ) from e
