from typing import Dict, List, Optional, Union

from fastapi import HTTPException, status
from sqlalchemy import exists
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import flag_modified

from lib.core.constants import EmitMessageKey
from lib.models.care_provider import CareProvider
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.models.patient import Patient as PatientModel
from lib.models.patient_alcohol_consumption import \
    PatientAlcoholConsumption as PatientAlcoholConsumptionModel
from lib.models.patient_connected_app import PatientConnectedApp
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
from lib.models.patient_eating_habit import \
    PatientEatingHabit as PatientEatingHabitModel
from lib.models.patient_family_diabetic_history import \
    PatientFamilyDiabeticHistory as PatientFamilyDiabeticHistoryModel
from lib.models.patient_food_allergy import \
    PatientFoodAllergy as PatientFoodAllergyModel
from lib.models.patient_meal_timing import \
    PatientMealTiming as PatientMealTimingModel
from lib.models.patient_medical_history import \
    PatientMedicalHistory as PatientMedicalHistoryModel
from lib.models.patient_plan import PatientPlan as PatientPlanModel
from lib.models.patient_sleep_habit import \
    PatientSleepHabit as PatientSleepHabitModel
from lib.models.patient_smoking_habit import \
    PatientSmokingHabit as PatientSmokingHabitModel
from lib.schemas.patient import CompletePatientProfile
from lib.schemas.patient import Patient as PatientSchema
from lib.schemas.patient import PatientUpdate
from lib.schemas.patient_alcohol_consumption import \
    PatientAlcoholConsumptionCreate
from lib.schemas.patient_current_medication import \
    PatientCurrentMedicationCreate
from lib.schemas.patient_daily_activity import PatientDailyActivityCreate
from lib.schemas.patient_diabetic_history import PatientDiabeticHistoryCreate
from lib.schemas.patient_diet_preference import PatientDietPreferenceCreate
from lib.schemas.patient_drug_allergy import PatientDrugAllergyCreate
from lib.schemas.patient_eating_habit import PatientEatingHabitCreate
from lib.schemas.patient_family_diabetic_history import \
    PatientFamilyDiabeticHistoryCreate
from lib.schemas.patient_food_allergy import PatientFoodAllergyCreate
from lib.schemas.patient_meal_timing import PatientMealTimingCreate
from lib.schemas.patient_medical_history import PatientMedicalHistoryCreate
from lib.schemas.patient_sleep_habit import PatientSleepHabitCreate
from lib.schemas.patient_smoking_habit import PatientSmokingHabitCreate
from lib.services.chat.chat_management_service import ChatManagementService
from lib.services.chat.chat_notification_service import ChatNotificationService
from lib.services.socketio_service import sio
from lib.utils.http_exceptions import raise_http_exception


class PatientProfileService:
    def __init__(
        self,
        postgres_session: AsyncSession,
        chat_notification_service: ChatNotificationService,
        chat_management_service: ChatManagementService,
    ):
        self.postgres_session = postgres_session
        self.chat_notification_service = chat_notification_service
        self.chat_management_service = chat_management_service

    async def fetch_patient_profile(
        self,
        patient_id: str,
        detailed: bool = False,
        include_health_data: bool = False,
        other_related_data: bool = False,
    ) -> PatientModel:
        try:
            stmt = (
                select(PatientModel)
                .where(PatientModel.patient_id == patient_id)
                .options(
                    selectinload(PatientModel.care_providers),
                    selectinload(PatientModel.package),
                    selectinload(PatientModel.health_facility),
                )
            )

            if detailed:
                stmt = stmt.options(
                    selectinload(PatientModel.daily_activity),
                    selectinload(PatientModel.food_allergies),
                    selectinload(PatientModel.drug_allergies),
                    selectinload(PatientModel.alcohol_consumption),
                    selectinload(PatientModel.smoking_habit),
                    selectinload(PatientModel.sleep_habit),
                    selectinload(PatientModel.eating_habit).selectinload(
                        PatientEatingHabitModel.meal_timings
                    ),
                    selectinload(PatientModel.eating_habit).selectinload(
                        PatientEatingHabitModel.diet_preferences
                    ),
                    selectinload(PatientModel.patient_plans).selectinload(
                        PatientPlanModel.diet_plan
                    ),
                    selectinload(PatientModel.patient_plans).selectinload(
                        PatientPlanModel.fitness_plan
                    ),
                    selectinload(PatientModel.diabetic_history),
                    selectinload(PatientModel.family_diabetic_histories),
                    selectinload(PatientModel.medical_histories),
                    selectinload(PatientModel.current_medication),
                )

            if include_health_data:
                stmt = stmt.options(
                    selectinload(PatientModel.vitals),
                    selectinload(PatientModel.smbgs),
                )

            if other_related_data:
                stmt = stmt.options(
                    selectinload(PatientModel.permissions),
                    selectinload(PatientModel.connected_apps).selectinload(
                        PatientConnectedApp.libreview
                    ),
                    selectinload(PatientModel.connected_apps).selectinload(
                        PatientConnectedApp.other_app
                    ),
                    selectinload(PatientModel.token_usage_logs),
                )

            result = await self.postgres_session.execute(stmt)
            patient = result.scalars().first()

            if not patient:
                raise_http_exception(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message="Patient not found.",
                )

            return patient

        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    async def fetch_patient_profiles(
        self, patient_ids: List[str]
    ) -> Dict[str, PatientSchema]:
        try:
            stmt = select(PatientModel).where(
                PatientModel.patient_id.in_(patient_ids)
            )
            result = await self.postgres_session.execute(stmt)
            profiles = result.scalars().all()

            return {
                str(profile.patient_id): PatientSchema.from_orm(profile)
                for profile in profiles
            }
        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    async def update_basic_patient_profile(
        self, patient_id: str, patient_data: PatientUpdate
    ) -> PatientModel:
        try:
            patient_profile = await self.fetch_patient_profile(patient_id)

            for key, value in patient_data.model_dump(
                exclude_unset=True
            ).items():
                if key not in ["created_at", "updated_at", "phone_number"]:
                    setattr(patient_profile, key, value)

            updated = self._mark_profile_section_complete(
                patient_profile.profile_completion, "basic"
            )
            if updated:
                flag_modified(patient_profile, "profile_completion")

            await self.postgres_session.commit()
            await self.postgres_session.refresh(patient_profile)

            await self.chat_notification_service.notify_participants(
                message_key=EmitMessageKey.CHAT_LIST_UPDATED.value,
                user_id=patient_id,
            )

            updated_patient = await self.fetch_patient_profile(
                patient_id, detailed=True
            )
            return updated_patient

        except IntegrityError as e:
            await self.postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Failed to update basic patient profile due to an integrity error.",
                detail=str(e),
            )
        except Exception as e:
            await self.postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="An unexpected error occurred while updating basic patient profile.",
                detail=str(e),
            )

    async def upsert_patient_lifestyle(
        self,
        patient_id: str,
        daily_activity: PatientDailyActivityCreate,
        alcohol_consumption: PatientAlcoholConsumptionCreate,
        smoking_habit: PatientSmokingHabitCreate,
        eating_habit: PatientEatingHabitCreate,
        sleep_habit: PatientSleepHabitCreate,
        food_allergies: Optional[List[PatientFoodAllergyCreate]] = None,
    ):
        try:
            patient_profile = await self.fetch_patient_profile(
                patient_id, detailed=True
            )

            # Upsert operations using helper methods
            patient_profile.daily_activity = self._upsert_single_entity(
                (
                    patient_profile.daily_activity
                    if patient_profile.daily_activity
                    else None
                ),
                daily_activity,
                PatientDailyActivityModel,
                "patient_id",
                patient_id,
            )

            patient_profile.alcohol_consumption = self._upsert_single_entity(
                patient_profile.alcohol_consumption,
                alcohol_consumption,
                PatientAlcoholConsumptionModel,
                "patient_id",
                patient_id,
            )

            patient_profile.smoking_habit = self._upsert_single_entity(
                patient_profile.smoking_habit,
                smoking_habit,
                PatientSmokingHabitModel,
                "patient_id",
                patient_id,
            )

            patient_profile.sleep_habit = self._upsert_single_entity(
                patient_profile.sleep_habit,
                sleep_habit,
                PatientSleepHabitModel,
                "patient_id",
                patient_id,
            )

            patient_profile.food_allergies = (
                await self._upsert_multiple_entities(
                    patient_profile.food_allergies,
                    food_allergies or [],
                    PatientFoodAllergyModel,
                    "patient_id",
                    patient_id,
                )
            )

            ignore_fields = [
                "meal_timings",
                "diet_preferences",
            ]
            patient_profile.eating_habit = self._upsert_single_entity(
                patient_profile.eating_habit,
                eating_habit,
                PatientEatingHabitModel,
                "patient_id",
                patient_id,
                ignore_fields=ignore_fields,
            )

            patient_profile.eating_habit.meal_timings = (
                await self._upsert_multiple_entities(
                    patient_profile.eating_habit.meal_timings,
                    eating_habit.meal_timings or [],
                    PatientMealTimingModel,
                    "eating_habit_id",
                    patient_profile.eating_habit.eating_habit_id,
                )
            )

            patient_profile.eating_habit.diet_preferences = (
                self._upsert_single_entity(
                    patient_profile.eating_habit.diet_preferences,
                    eating_habit.diet_preferences,
                    PatientDietPreferenceModel,
                    "eating_habit_id",
                    patient_profile.eating_habit.eating_habit_id,
                )
            )

            updated = self._mark_profile_section_complete(
                patient_profile.profile_completion, "lifestyle"
            )
            if updated:
                flag_modified(patient_profile, "profile_completion")

            self.postgres_session.add(patient_profile)
            await self.postgres_session.commit()
            await self.postgres_session.refresh(patient_profile)

            updated_patient = await self.fetch_patient_profile(
                patient_id, detailed=True
            )
            return updated_patient

        except IntegrityError as e:
            await self.postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Integrity Error",
                detail=str(e),
            )
        except SQLAlchemyError as e:
            await self.postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
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
            patient_profile = await self.fetch_patient_profile(
                patient_id, detailed=True
            )

            # Upsert operations using helper methods
            patient_profile.diabetic_history = self._upsert_single_entity(
                patient_profile.diabetic_history,
                diabetic_history,
                PatientDiabeticHistoryModel,
                "patient_id",
                patient_id,
            )

            patient_profile.current_medication = self._upsert_single_entity(
                patient_profile.current_medication,
                current_medication,
                PatientCurrentMedicationModel,
                "patient_id",
                patient_id,
            )

            patient_profile.drug_allergies = (
                await self._upsert_multiple_entities(
                    patient_profile.drug_allergies,
                    drug_allergies or [],
                    PatientDrugAllergyModel,
                    "patient_id",
                    patient_id,
                )
            )

            patient_profile.family_diabetic_histories = (
                await self._upsert_multiple_entities(
                    patient_profile.family_diabetic_histories,
                    family_diabetic_histories or [],
                    PatientFamilyDiabeticHistoryModel,
                    "patient_id",
                    patient_id,
                )
            )

            patient_profile.medical_histories = (
                await self._upsert_multiple_entities(
                    patient_profile.medical_histories,
                    medical_histories or [],
                    PatientMedicalHistoryModel,
                    "patient_id",
                    patient_id,
                )
            )

            updated = self._mark_profile_section_complete(
                patient_profile.profile_completion, "medical_history"
            )
            if updated:
                flag_modified(patient_profile, "profile_completion")

            self.postgres_session.add(patient_profile)
            await self.postgres_session.commit()
            await self.postgres_session.refresh(patient_profile)

            updated_patient = await self.fetch_patient_profile(
                patient_id, detailed=True
            )

            return updated_patient

        except IntegrityError as e:
            await self.postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Integrity Error",
                detail=str(e),
            )
        except SQLAlchemyError as e:
            await self.postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    async def delete_patient_profile(
        self, patient_id: str, delete_chats: bool = False
    ) -> None:

        try:
            patient = await self.fetch_patient_profile(patient_id)

            if delete_chats:
                await self.chat_management_service.delete_all_chats(
                    user_id=str(patient.patient_id),
                )

            await self.postgres_session.delete(patient)
            await self.postgres_session.commit()

        except SQLAlchemyError as e:
            await self.postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    async def assign_care_provider_to_patient(
        self,
        current_care_provider: CareProviderModel,
        patient_id: str,
        assigned_care_provider_id: str,
    ) -> PatientModel:

        try:
            patient = await self.fetch_patient_profile(patient_id)

            # Fetch the assigned Care Provider
            stmt = select(CareProviderModel).where(
                CareProviderModel.care_provider_id == assigned_care_provider_id
            )
            result = await self.postgres_session.execute(stmt)
            assigned_care_provider = result.scalars().first()

            if not assigned_care_provider:
                raise_http_exception(
                    status_code=404,
                    message="Assigned Care Provider not found.",
                )

            # Automatically assign the patient to the care provider's health facility if unassigned
            if not patient.health_facility_id:  # type: ignore
                patient.health_facility_id = (
                    current_care_provider.health_facility_id
                )

            # Ensure the same health facility
            if (
                assigned_care_provider.health_facility_id
                != current_care_provider.health_facility_id
                or current_care_provider.health_facility_id
                != patient.health_facility_id  # type: ignore
            ):  # type: ignore
                raise_http_exception(
                    status_code=400,
                    message="The assigned care provider, current care provider, and the patient must belong to the same health facility.",
                )

            # Check if care provider is already assigned
            if assigned_care_provider in patient.care_providers:
                raise_http_exception(
                    status_code=400,
                    message="The assigned care provider is already linked to this patient.",
                )

            # Link the care provider to the patient
            patient.care_providers.append(assigned_care_provider)

            # Commit changes
            self.postgres_session.add(patient)
            await self.postgres_session.commit()
            await self.postgres_session.refresh(patient)

            # Create direct and group chats
            await self.chat_management_service.create_direct_and_group_chats(
                patient, assigned_care_provider
            )

            # Notify participants
            await self.chat_notification_service.notify_participants(
                message_key=EmitMessageKey.CHAT_LIST_UPDATED.value,
                user_id=str(patient.patient_id),
            )

            return patient

        except SQLAlchemyError as e:
            await self.postgres_session.rollback()
            raise_http_exception(
                status_code=500,
                message="Database Error",
                detail=str(e),
            )

    async def add_care_provider_by_code(
        self, patient_id: str, care_provider_code: str
    ) -> CareProviderModel:
        try:
            # Fetch care provider by code
            stmt = select(CareProviderModel).where(
                CareProviderModel.code == care_provider_code
            )
            result = await self.postgres_session.execute(stmt)
            care_provider = result.scalars().first()

            if not care_provider:
                raise_http_exception(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message="Invalid care provider code.",
                )

            # Fetch the patient
            patient = await self.fetch_patient_profile(
                patient_id, detailed=True
            )

            # Check if the care provider is already linked
            if care_provider in patient.care_providers:
                raise_http_exception(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    message="Care provider is already added.",
                )

            # Link the care provider to the patient
            patient.care_providers.append(care_provider)

            self.postgres_session.add(patient)
            await self.postgres_session.commit()
            await self.postgres_session.refresh(patient)

            # Create direct and group chats
            await self.chat_management_service.create_direct_and_group_chats(
                patient, care_provider
            )

            # Notify participants about chat updates
            await self.chat_notification_service.notify_participants(
                message_key=EmitMessageKey.CHAT_LIST_UPDATED.value,
                user_id=str(patient.patient_id),
            )

            return care_provider

        except SQLAlchemyError as e:
            await self.postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    async def check_patient_exists(self, patient_id: str) -> bool:
        try:
            stmt = select(
                exists().where(PatientModel.patient_id == patient_id)
            )
            result = await self.postgres_session.execute(stmt)
            (exists_result,) = result.scalars()

            if not exists_result:
                raise_http_exception(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message="Patient not found",
                )

            return True
        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    def _upsert_single_entity(
        self,
        entity,
        data,
        model,
        foreign_key_name,
        foreign_key_value,
        ignore_fields=None,
    ):
        """Helper method to upsert a single entity, ignoring nested relationships."""
        if ignore_fields is None:
            ignore_fields = []

        if entity:
            for key, value in data.dict().items():
                if key not in ignore_fields:
                    setattr(entity, key, value)

        else:
            entity_data = {
                key: value
                for key, value in data.dict().items()
                if key not in ignore_fields
            }
            entity_data[foreign_key_name] = foreign_key_value
            entity = model(**entity_data)

        return entity

    async def _upsert_multiple_entities(
        self,
        existing_entities,
        new_data_list,
        model,
        foreign_key_name,
        foreign_key_value,
    ):
        """Helper method to delete existing entities and upsert multiple new entities."""

        # Delete existing entities
        for entity in existing_entities:
            await self.postgres_session.delete(entity)

        # Create new entities
        new_entities = [
            model(**data.dict(), **{foreign_key_name: foreign_key_value})
            for data in new_data_list
        ]

        # Add new entities to the session
        self.postgres_session.add_all(new_entities)

        return new_entities

    def _mark_profile_section_complete(
        self, profile_completion, section: str
    ) -> bool:
        if not profile_completion[section]["is_complete"]:
            profile_completion[section]["is_complete"] = True
            return True
        return False
