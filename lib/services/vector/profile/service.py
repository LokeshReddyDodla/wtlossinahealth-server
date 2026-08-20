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

        def prefer(*candidates):
            for c in candidates:
                if c is not None and c != "":
                    return c
            return None

        patient_id = profile_data.get("patient_id")
        first_name = profile_data.get("first_name", "")
        last_name = profile_data.get("last_name", "")
        age = profile_data.get("age")
        gender = profile_data.get("gender")
        occupation = profile_data.get("occupation")
        timezone = prefer(profile_data.get("timezone"), profile_data.get("locale"))

        # Body — prefer the unit-suffixed columns, fall back to legacy during soak
        height_cm = prefer(profile_data.get("height_cm"), profile_data.get("height"))
        weight_kg = prefer(profile_data.get("weight_kg"), profile_data.get("weight"))
        waist_cm = prefer(profile_data.get("waist_cm"), profile_data.get("waist"))
        hip_cm = profile_data.get("hip_cm")
        bmi = (
            round(weight_kg / (height_cm / 100) ** 2, 1)
            if height_cm and weight_kg
            else None
        )

        # Daily activity
        daily_activity = safe_dict(profile_data.get("daily_activity"))
        activity_level = daily_activity.get("activity_level")

        # Allergies — surface new structured fields, with legacy allergy_name fallback
        def map_allergy(a: dict, reaction_key: str = None) -> dict:
            entry = {
                "name": prefer(a.get("name"), a.get("allergy_name")),
                "name_other": a.get("name_other"),
                "severity": a.get("severity"),
            }
            if reaction_key:
                entry["reaction"] = a.get(reaction_key)
            return entry

        food_allergies = [
            map_allergy(a) for a in safe_list(profile_data.get("food_allergies"))
        ]
        drug_allergies = [
            map_allergy(a, reaction_key="reaction")
            for a in safe_list(profile_data.get("drug_allergies"))
        ]
        # Flat lists for cheap exists-queries in Qdrant filters
        food_allergy_names = [a.get("name") for a in food_allergies if a.get("name")]
        drug_allergy_names = [a.get("name") for a in drug_allergies if a.get("name")]

        # Alcohol
        alcohol = safe_dict(profile_data.get("alcohol_consumption"))
        alcohol_status = prefer(
            alcohol.get("status"),
            ("REGULAR" if alcohol.get("consume_alcohol") else "NEVER")
            if alcohol.get("consume_alcohol") is not None
            else None,
        )
        alcohol_frequency = alcohol.get("frequency")
        drinks_per_session = prefer(
            alcohol.get("drinks_per_session"), alcohol.get("quantity")
        )
        alcohol_types = alcohol.get("type_of_alcohol") or []
        if isinstance(alcohol_types, str):
            alcohol_types = [alcohol_types]
        alcohol_quit_years_ago = alcohol.get("quit_years_ago")

        # Smoking
        smoking = safe_dict(profile_data.get("smoking_habit"))
        smoking_status = prefer(
            smoking.get("status"),
            ("CURRENT" if smoking.get("smoke_status") else "NEVER")
            if smoking.get("smoke_status") is not None
            else None,
        )
        smoke_types = smoking.get("smoke_type") or []
        if isinstance(smoke_types, str):
            smoke_types = [smoke_types]
        years_of_smoking = smoking.get("years_of_smoking")
        cigarettes_per_day = smoking.get("cigarettes_per_day")
        smoking_quit_years_ago = smoking.get("quit_years_ago")

        # Eating habits
        eating = safe_dict(profile_data.get("eating_habit"))
        snacks_count = eating.get("snacks_count")
        meals_per_day = eating.get("meals_per_day")
        meal_timings = [
            {"meal_type": m.get("meal_type"), "time": m.get("time")}
            for m in safe_list(eating.get("meal_timings"))
        ]
        cuisine_preferences = safe_list(eating.get("cuisine_preferences"))

        dietary_preferences = safe_list(eating.get("dietary_preferences"))
        if not dietary_preferences:
            legacy_diet = eating.get("diet_preferences")
            if isinstance(legacy_diet, dict) and legacy_diet.get("preference"):
                dietary_preferences = [legacy_diet["preference"]]
        diet_preferences_detail = prefer(
            eating.get("diet_preferences_detail"),
            (eating.get("diet_preferences") or {}).get("detail")
            if isinstance(eating.get("diet_preferences"), dict)
            else None,
        )

        # Sleep
        sleep = safe_dict(profile_data.get("sleep_habit"))
        sleep_quality = sleep.get("sleep_quality")
        wake_up_fresh = sleep.get("wake_up_fresh")
        drowsy_day = sleep.get("drowsy_day")
        snores = sleep.get("snores")
        average_sleep_hours = prefer(
            sleep.get("average_sleep_hours"), sleep.get("average_sleep_duration")
        )
        wake_up_time = sleep.get("wake_up_time")
        bed_time = sleep.get("bed_time")

        # Diabetes history
        diabetic = safe_dict(profile_data.get("diabetic_history"))
        type_of_diabetes = diabetic.get("type_of_diabetes")
        years_with_diabetes = diabetic.get("years_with_diabetes")
        diagnosed_at = diabetic.get("diagnosed_at")

        # Reproductive health (new section; falls back to legacy pregnancy fields)
        repro = safe_dict(profile_data.get("reproductive_health"))
        is_pregnant = prefer(repro.get("is_pregnant"), diabetic.get("is_pregnant"))
        pregnancy_weeks = prefer(
            repro.get("pregnancy_weeks"), diabetic.get("pregnancy_weeks")
        )
        menopause_status = repro.get("menopause_status")
        period_regularity = repro.get("period_regularity")
        uses_contraception = repro.get("uses_contraception")

        # Family history
        family_histories = safe_list(
            profile_data.get("family_diabetic_histories")
        )
        family_diabetic_members = [
            f.get("family_member") for f in family_histories
        ]
        family_diabetic_types = [
            f.get("type_of_diabetes") for f in family_histories
        ]
        family_diabetic_years = [
            f.get("years_with_diabetes") for f in family_histories
        ]

        # Medical histories
        medical_histories = safe_list(profile_data.get("medical_histories"))
        medical_conditions = [m.get("condition") for m in medical_histories]
        medical_conditions_other = [
            m.get("condition_other") for m in medical_histories
        ]
        medical_conditions_status = [
            m.get("status") for m in medical_histories
        ]
        medical_conditions_years = [
            m.get("duration_years") for m in medical_histories
        ]
        medical_conditions_started_at = [
            m.get("started_at") for m in medical_histories
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
            "occupation": occupation,
            "timezone": timezone,
            "height_cm": height_cm,
            "weight_kg": weight_kg,
            "waist_cm": waist_cm,
            "hip_cm": hip_cm,
            "bmi": bmi,
            "activity_level": activity_level,
            "food_allergies": food_allergies,
            "food_allergy_names": food_allergy_names,
            "drug_allergies": drug_allergies,
            "drug_allergy_names": drug_allergy_names,
            "alcohol_status": alcohol_status,
            "alcohol_frequency": alcohol_frequency,
            "drinks_per_session": drinks_per_session,
            "alcohol_types": alcohol_types,
            "alcohol_quit_years_ago": alcohol_quit_years_ago,
            "smoking_status": smoking_status,
            "smoke_type": smoke_types,
            "years_of_smoking": years_of_smoking,
            "cigarettes_per_day": cigarettes_per_day,
            "smoking_quit_years_ago": smoking_quit_years_ago,
            "snacks_count": snacks_count,
            "meals_per_day": meals_per_day,
            "meal_timings": meal_timings,
            "cuisine_preferences": cuisine_preferences,
            "dietary_preferences": dietary_preferences,
            "diet_preferences_detail": diet_preferences_detail,
            "sleep_quality": sleep_quality,
            "wake_up_fresh": wake_up_fresh,
            "drowsy_day": drowsy_day,
            "snores": snores,
            "average_sleep_hours": average_sleep_hours,
            "wake_up_time": wake_up_time,
            "bed_time": bed_time,
            "type_of_diabetes": type_of_diabetes,
            "years_with_diabetes": years_with_diabetes,
            "diagnosed_at": diagnosed_at,
            "is_pregnant": is_pregnant,
            "pregnancy_weeks": pregnancy_weeks,
            "menopause_status": menopause_status,
            "period_regularity": period_regularity,
            "uses_contraception": uses_contraception,
            "family_diabetic_members": family_diabetic_members,
            "family_diabetic_types": family_diabetic_types,
            "family_diabetic_years": family_diabetic_years,
            "medical_conditions": medical_conditions,
            "medical_conditions_other": medical_conditions_other,
            "medical_conditions_status": medical_conditions_status,
            "medical_conditions_years": medical_conditions_years,
            "medical_conditions_started_at": medical_conditions_started_at,
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
