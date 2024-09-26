from typing import Dict, List, Optional

from fastapi import HTTPException, status
from sqlalchemy import exists
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from lib.models.care_provider import CareProvider
from lib.models.patient import Patient as PatientModel
from lib.models.patient_alcohol_consumption import \
    PatientAlcoholConsumption as PatientAlcoholConsumptionModel
from lib.models.patient_care_provider import PatientCareProvider
from lib.models.patient_connected_app import PatientConnectedApp
from lib.models.patient_cuisine_preference import \
    PatientCuisinePreference as PatientCuisinePreferenceModel
from lib.models.patient_current_medication import \
    PatientCurrentMedication as PatientCurrentMedicationModel
from lib.models.patient_daily_activity import \
    PatientDailyActivity as PatientDailyActivityModel
from lib.models.patient_diabetic_history import \
    PatientDiabeticHistory as PatientDiabeticHistoryModel
from lib.models.patient_diet_preference import \
    PatientDietPreference as PatientDietPreferenceModel
from lib.models.patient_drug_allergy import \
    PatientDrugAllergy as PatientDrugAllergyModel
from lib.models.patient_family_diabetic_history import \
    PatientFamilyDiabeticHistory as PatientFamilyDiabeticHistoryModel
from lib.models.patient_food_allergy import \
    PatientFoodAllergy as PatientFoodAllergyModel
from lib.models.patient_meal_timing import \
    PatientMealTiming as PatientMealTimingModel
from lib.models.patient_medical_history import \
    PatientMedicalHistory as PatientMedicalHistoryModel
from lib.models.patient_sleep_habit import \
    PatientSleepHabit as PatientSleepHabitModel
from lib.models.patient_smoking_habit import \
    PatientSmokingHabit as PatientSmokingHabitModel
from lib.schemas.patient import CompletePatientProfile
from lib.schemas.patient import Patient as PatientSchema
from lib.schemas.patient import PatientUpdate
from lib.schemas.patient_alcohol_consumption import \
    PatientAlcoholConsumptionCreate
from lib.schemas.patient_cuisine_preference import \
    PatientCuisinePreferenceCreate
from lib.schemas.patient_current_medication import \
    PatientCurrentMedicationCreate
from lib.schemas.patient_daily_activity import PatientDailyActivityCreate
from lib.schemas.patient_diabetic_history import PatientDiabeticHistoryCreate
from lib.schemas.patient_diet_preference import PatientDietPreferenceCreate
from lib.schemas.patient_drug_allergy import PatientDrugAllergyCreate
from lib.schemas.patient_family_diabetic_history import \
    PatientFamilyDiabeticHistoryCreate
from lib.schemas.patient_food_allergy import PatientFoodAllergyCreate
from lib.schemas.patient_meal_timing import PatientMealTimingCreate
from lib.schemas.patient_medical_history import PatientMedicalHistoryCreate
from lib.schemas.patient_sleep_habit import PatientSleepHabitCreate
from lib.schemas.patient_smoking_habit import PatientSmokingHabitCreate
from lib.services.chat_service import ChatService
from lib.services.patient_care_provider_service import \
    PatientCareProviderService
from lib.services.socketio_service import sio


class PatientProfileService:
    def __init__(self, postgres_session: AsyncSession):
        self.postgres_session = postgres_session
        self.chat_service = ChatService()
        self.patient_care_provider_service = PatientCareProviderService(
            postgres_session
        )

    async def fetch_patient_profile(
        self, patient_id: str, detailed: bool = False
    ) -> PatientModel:
        try:
            stmt = select(PatientModel).where(
                PatientModel.patient_id == patient_id
            )

            if detailed:
                stmt = stmt.options(
                    selectinload(PatientModel.daily_activity),
                    selectinload(PatientModel.food_allergies),
                    selectinload(PatientModel.drug_allergies),
                    selectinload(PatientModel.diet_preferences),
                    selectinload(PatientModel.alcohol_consumption),
                    selectinload(PatientModel.smoking_habit),
                    selectinload(PatientModel.meal_timings),
                    selectinload(PatientModel.cuisine_preferences),
                    selectinload(PatientModel.sleep_habit),
                    selectinload(PatientModel.diabetic_history),
                    selectinload(PatientModel.family_diabetic_histories),
                    selectinload(PatientModel.medical_histories),
                    selectinload(PatientModel.current_medication),
                    selectinload(PatientModel.permissions),
                    selectinload(PatientModel.vitals),
                    selectinload(PatientModel.smbgs),
                    selectinload(PatientModel.connected_apps).selectinload(
                        PatientConnectedApp.libreview
                    ),
                    selectinload(PatientModel.connected_apps).selectinload(
                        PatientConnectedApp.other_app
                    ),
                    selectinload(PatientModel.fitness_sync),
                    selectinload(PatientModel.token_usage_logs),
                    selectinload(PatientModel.care_providers)
                    .selectinload(PatientCareProvider.care_provider)
                    .selectinload(CareProvider.health_facility),
                    selectinload(PatientModel.health_facility),
                )

            result = await self.postgres_session.execute(stmt)
            patient = result.scalars().first()

            if not patient:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Patient not found.",
                )

            return patient

        except SQLAlchemyError as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database error: {str(e)}",
            )

    async def fetch_patient_profiles(
        self, patient_ids: List[str]
    ) -> Dict[str, PatientModel]:
        try:
            stmt = select(PatientModel).where(
                PatientModel.patient_id.in_(patient_ids)
            )
            result = await self.postgres_session.execute(stmt)
            profiles = result.scalars().all()

            return {str(profile.patient_id): profile for profile in profiles}
        except SQLAlchemyError as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database error: {str(e)}",
            )

    async def update_basic_patient_profile(
        self, patient_id: str, patient_data: PatientUpdate
    ) -> PatientModel:
        try:
            patient_profile = await self.fetch_patient_profile(patient_id)

            for key, value in patient_data.dict(exclude_unset=True).items():
                if key not in ["created_at", "updated_at", "phone_number"]:
                    setattr(patient_profile, key, value)

            await self.postgres_session.commit()
            await self.postgres_session.refresh(patient_profile)

            await self.chat_service.emit_to_associated_participants(
                message_key="chatListUpdate",
                data=None,
                chat_id=None,
                fetch_func=lambda: self.patient_care_provider_service.fetch_associated_records(
                    patient_id=patient_id
                ),
            )

            return patient_profile

        except IntegrityError as e:
            await self.postgres_session.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Integrity Error: {str(e)}",
            )
        except SQLAlchemyError as e:
            await self.postgres_session.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database Error: {str(e)}",
            )

    async def upsert_patient_lifestyle(
        self,
        patient_id: str,
        daily_activity: PatientDailyActivityCreate,
        diet_preferences: List[PatientDietPreferenceCreate],
        alcohol_consumption: PatientAlcoholConsumptionCreate,
        smoking_habit: PatientSmokingHabitCreate,
        sleep_habit: PatientSleepHabitCreate,
        food_allergies: Optional[List[PatientFoodAllergyCreate]] = None,
        meal_timings: Optional[List[PatientMealTimingCreate]] = None,
        cuisine_preferences: Optional[
            List[PatientCuisinePreferenceCreate]
        ] = None,
    ):
        try:
            patient = await self.fetch_patient_profile(
                patient_id, detailed=True
            )

            # Upsert operations using helper methods
            patient.daily_activity = [
                self._upsert_single_entity(
                    (
                        patient.daily_activity[0]
                        if patient.daily_activity
                        else None
                    ),
                    daily_activity,
                    PatientDailyActivityModel,
                    patient_id,
                )
            ]

            patient.alcohol_consumption = self._upsert_single_entity(
                patient.alcohol_consumption,
                alcohol_consumption,
                PatientAlcoholConsumptionModel,
                patient_id,
            )

            patient.smoking_habit = self._upsert_single_entity(
                patient.smoking_habit,
                smoking_habit,
                PatientSmokingHabitModel,
                patient_id,
            )

            patient.sleep_habit = self._upsert_single_entity(
                patient.sleep_habit,
                sleep_habit,
                PatientSleepHabitModel,
                patient_id,
            )

            patient.diet_preferences = await self._upsert_multiple_entities(
                patient.diet_preferences,
                diet_preferences,
                PatientDietPreferenceModel,
                patient_id,
            )

            patient.food_allergies = await self._upsert_multiple_entities(
                patient.food_allergies,
                food_allergies or [],
                PatientFoodAllergyModel,
                patient_id,
            )

            patient.meal_timings = await self._upsert_multiple_entities(
                patient.meal_timings,
                meal_timings or [],
                PatientMealTimingModel,
                patient_id,
            )

            patient.cuisine_preferences = await self._upsert_multiple_entities(
                patient.cuisine_preferences,
                cuisine_preferences or [],
                PatientCuisinePreferenceModel,
                patient_id,
            )

            self.postgres_session.add(patient)
            await self.postgres_session.commit()
            await self.postgres_session.refresh(patient)

            return patient

        except IntegrityError as e:
            await self.postgres_session.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Integrity Error: {str(e)}",
            )
        except SQLAlchemyError as e:
            await self.postgres_session.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database error: {str(e)}",
            )

    async def upsert_patient_medical_history(
        self,
        patient_id: str,
        diabetic_history: PatientDiabeticHistoryCreate,
        current_medication: PatientCurrentMedicationCreate,
        drug_allergies: Optional[List[PatientDrugAllergyCreate]] = None,
        family_diabetic_histories: Optional[
            List[PatientFamilyDiabeticHistoryCreate]
        ] = None,
        medical_histories: Optional[List[PatientMedicalHistoryCreate]] = None,
    ) -> PatientModel:
        try:
            patient = await self.fetch_patient_profile(
                patient_id, detailed=True
            )

            # Upsert operations using helper methods
            patient.diabetic_history = self._upsert_single_entity(
                patient.diabetic_history,
                diabetic_history,
                PatientDiabeticHistoryModel,
                patient_id,
            )

            patient.current_medication = self._upsert_single_entity(
                patient.current_medication,
                current_medication,
                PatientCurrentMedicationModel,
                patient_id,
            )

            patient.drug_allergies = await self._upsert_multiple_entities(
                patient.drug_allergies,
                drug_allergies or [],
                PatientDrugAllergyModel,
                patient_id,
            )

            patient.family_diabetic_histories = (
                await self._upsert_multiple_entities(
                    patient.family_diabetic_histories,
                    family_diabetic_histories or [],
                    PatientFamilyDiabeticHistoryModel,
                    patient_id,
                )
            )

            patient.medical_histories = await self._upsert_multiple_entities(
                patient.medical_histories,
                medical_histories or [],
                PatientMedicalHistoryModel,
                patient_id,
            )

            self.postgres_session.add(patient)
            await self.postgres_session.commit()
            await self.postgres_session.refresh(patient)

            return patient

        except IntegrityError as e:
            await self.postgres_session.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Integrity Error: {str(e)}",
            )
        except SQLAlchemyError as e:
            await self.postgres_session.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database error: {str(e)}",
            )

    async def delete_patient_profile(
        self, patient_id: str, delete_chats: bool = False
    ) -> None:

        try:
            patient = await self.fetch_patient_profile(patient_id)

            if delete_chats:
                await self.chat_service.delete_all_chats(
                    user_id=str(patient.patient_id),
                )

            await self.postgres_session.delete(patient)
            await self.postgres_session.commit()

        except SQLAlchemyError as e:
            await self.postgres_session.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database Error: {str(e)}",
            )

    async def check_patient_profile_exists(self, patient_id: str) -> bool:
        try:
            stmt = select(
                exists().where(PatientModel.patient_id == patient_id)
            )
            result = await self.postgres_session.execute(stmt)
            (exists_result,) = result.scalars()

            if not exists_result:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Patient not found.",
                )

            return True
        except SQLAlchemyError as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database error: {str(e)}",
            )

    def _upsert_single_entity(self, entity, data, model, patient_id):
        """Helper method to upsert a single entity."""
        if entity:
            for key, value in data.dict().items():
                setattr(entity, key, value)
        else:
            entity = model(**data.dict(), patient_id=patient_id)
        return entity

    async def _upsert_multiple_entities(
        self, existing_entities, new_data_list, model, patient_id
    ):
        """Helper method to delete existing entities and upsert multiple new entities."""

        # Delete existing entities
        for entity in existing_entities:
            await self.postgres_session.delete(entity)

        # Create new entities
        new_entities = [
            model(**data.dict(), patient_id=patient_id)
            for data in new_data_list
        ]

        # Add new entities to the session
        self.postgres_session.add_all(new_entities)

        return new_entities
