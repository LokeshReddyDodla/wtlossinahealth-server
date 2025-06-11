from typing import Dict, List, Optional

from fastapi import HTTPException, status
from sqlalchemy import exists, or_
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy.orm.attributes import flag_modified

from lib.core.constants import EmitMessageKeyEnum
from lib.core.postgres_store import PostgresStore
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.models.patient import Patient as PatientModel
from lib.models.patient_alcohol_consumption import (
    PatientAlcoholConsumption as PatientAlcoholConsumptionModel,
)
from lib.models.patient_connected_app import PatientConnectedApp
from lib.models.patient_current_medication import (
    PatientCurrentMedication as PatientCurrentMedicationModel,
)
from lib.models.patient_daily_activity import (
    PatientDailyActivity as PatientDailyActivityModel,
)
from lib.models.patient_diabetic_history import (
    PatientDiabeticHistory as PatientDiabeticHistoryModel,
)
from lib.models.patient_diet_preference import (
    PatientDietPreference as PatientDietPreferenceModel,
)
from lib.models.patient_drug_allergy import (
    PatientDrugAllergy as PatientDrugAllergyModel,
)
from lib.models.patient_eating_habit import (
    PatientEatingHabit as PatientEatingHabitModel,
)
from lib.models.patient_family_diabetic_history import (
    PatientFamilyDiabeticHistory as PatientFamilyDiabeticHistoryModel,
)
from lib.models.patient_food_allergy import (
    PatientFoodAllergy as PatientFoodAllergyModel,
)
from lib.models.patient_meal_timing import (
    PatientMealTiming as PatientMealTimingModel,
)
from lib.models.patient_medical_history import (
    PatientMedicalHistory as PatientMedicalHistoryModel,
)
from lib.models.patient_plan import PatientPlan as PatientPlanModel
from lib.models.patient_sleep_habit import (
    PatientSleepHabit as PatientSleepHabitModel,
)
from lib.models.patient_smoking_habit import (
    PatientSmokingHabit as PatientSmokingHabitModel,
)
from lib.schemas.patient import Patient as PatientSchema, PatientCreate
from lib.schemas.patient import PatientUpdate
from lib.schemas.patient_alcohol_consumption import (
    PatientAlcoholConsumptionCreate,
)
from lib.schemas.patient_current_medication import (
    PatientCurrentMedicationCreate,
)
from lib.schemas.patient_daily_activity import PatientDailyActivityCreate
from lib.schemas.patient_diabetic_history import PatientDiabeticHistoryCreate
from lib.schemas.patient_drug_allergy import PatientDrugAllergyCreate
from lib.schemas.patient_eating_habit import PatientEatingHabitCreate
from lib.schemas.patient_family_diabetic_history import (
    PatientFamilyDiabeticHistoryCreate,
)
from lib.schemas.patient_food_allergy import PatientFoodAllergyCreate
from lib.schemas.patient_medical_history import PatientMedicalHistoryCreate
from lib.schemas.patient_sleep_habit import PatientSleepHabitCreate
from lib.schemas.patient_smoking_habit import PatientSmokingHabitCreate
from lib.services.care_provider_profile_service import (
    CareProviderProfileService,
)
from lib.services.chat.chat_exceptions import ChatCreationError
from lib.services.chat.chat_management_service import ChatManagementService
from lib.services.chat.chat_notification_service import ChatNotificationService
from lib.utils.http_exceptions import raise_http_exception
from lib.utils.postgres_session_decorator import with_postgres_session


class PatientProfileService:
    def __init__(
        self,
        postgres_store: PostgresStore,
        care_provider_service: CareProviderProfileService,
        chat_notification_service: ChatNotificationService,
        chat_management_service: ChatManagementService,
    ):
        self.postgres_store = postgres_store
        self.care_provider_service = care_provider_service
        self.chat_notification_service = chat_notification_service
        self.chat_management_service = chat_management_service

    @with_postgres_session
    async def fetch_patient_profile(
        self,
        patient_id: str,
        detailed: bool = False,
        include_health_data: bool = False,
        other_related_data: bool = False,
        *,
        postgres_session: AsyncSession,
    ) -> PatientModel:
        try:
            stmt = (
                select(PatientModel)
                .where(PatientModel.patient_id == patient_id)
                .options(
                    joinedload(PatientModel.care_providers),
                    joinedload(PatientModel.package_assignments),
                    joinedload(PatientModel.health_facility),
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
                    joinedload(PatientModel.eating_habit).joinedload(
                        PatientEatingHabitModel.meal_timings
                    ),
                    joinedload(PatientModel.eating_habit).joinedload(
                        PatientEatingHabitModel.diet_preferences
                    ),
                    joinedload(PatientModel.patient_plans).joinedload(
                        PatientPlanModel.diet_plan
                    ),
                    joinedload(PatientModel.patient_plans).joinedload(
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
                    joinedload(PatientModel.connected_apps).joinedload(
                        PatientConnectedApp.libreview
                    ),
                    joinedload(PatientModel.connected_apps).joinedload(
                        PatientConnectedApp.other_app
                    ),
                )

            patient = await postgres_session.scalar(stmt)

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

    @with_postgres_session
    async def fetch_patient_profiles(
        self, patient_ids: List[str], *, postgres_session: AsyncSession
    ) -> Dict[str, PatientModel]:
        try:
            stmt = (
                select(PatientModel)
                .where(PatientModel.patient_id.in_(patient_ids))
                .options(
                    selectinload(PatientModel.care_providers),
                )
            )
            result = await postgres_session.execute(stmt)
            profiles = result.scalars().all()

            return {str(profile.patient_id): profile for profile in profiles}
        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    @with_postgres_session
    async def create_patient(
        self,
        patient_data: PatientCreate,
        *,
        creating_care_provider: Optional[CareProviderModel] = None,
        postgres_session: AsyncSession,
    ) -> PatientModel:
        try:
            # Check if patient already exists
            stmt = select(PatientModel).where(
                or_(
                    PatientModel.email == patient_data.email,
                    PatientModel.phone_number == patient_data.phone_number,
                )
            )
            existing_patient = await postgres_session.scalar(stmt)
            if existing_patient:
                raise_http_exception(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    message="Patient with this email or phone number already exists",
                )

            # Create new patient
            patient_dict = patient_data.model_dump()
            if creating_care_provider:
                patient_dict["health_facility_id"] = (
                    creating_care_provider.health_facility_id
                )

            new_patient = PatientModel(**patient_dict)
            postgres_session.add(new_patient)
            await postgres_session.flush()

            # Assign care provider (re-fetch in this session to avoid merge issues)
            if creating_care_provider:
                new_patient = await self.fetch_patient_profile(
                    new_patient.patient_id, postgres_session=postgres_session
                )
                merged_care_provider = await postgres_session.merge(
                    creating_care_provider
                )
                new_patient.care_providers.append(merged_care_provider)

                # Create chats and notifications
                await self.chat_management_service.create_chat_relationships(
                    str(new_patient.patient_id),
                    str(creating_care_provider.care_provider_id),
                )

            await postgres_session.commit()
            await postgres_session.refresh(new_patient)

            return new_patient

        except ChatCreationError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=500,
                message="Chat creation failed",
                detail=str(e),
            )
        except IntegrityError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Database integrity error",
                detail=str(e),
            )
        except SQLAlchemyError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database error while creating patient",
                detail=str(e),
            )
        except HTTPException as http_exc:
            raise http_exc

    @with_postgres_session
    async def update_basic_patient_profile(
        self,
        patient_id: str,
        patient_data: PatientUpdate,
        *,
        postgres_session: AsyncSession,
    ) -> PatientModel:
        try:
            patient_profile = await self.fetch_patient_profile(
                patient_id, postgres_session=postgres_session
            )

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

            await postgres_session.commit()
            await postgres_session.refresh(patient_profile)

            await self.chat_notification_service.notify_participants(
                message_key=EmitMessageKeyEnum.CHAT_LIST_UPDATED.value,
                user_id=patient_id,
            )

            updated_patient = await self.fetch_patient_profile(
                patient_id, detailed=True, postgres_session=postgres_session
            )
            return updated_patient

        except IntegrityError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Failed to update basic patient profile due to an integrity error.",
                detail=str(e),
            )

        except HTTPException as http_exc:
            raise http_exc

        except Exception as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="An unexpected error occurred while updating basic patient profile.",
                detail=str(e),
            )

    @with_postgres_session
    async def upsert_patient_lifestyle(
        self,
        patient_id: str,
        daily_activity: PatientDailyActivityCreate,
        alcohol_consumption: PatientAlcoholConsumptionCreate,
        smoking_habit: PatientSmokingHabitCreate,
        eating_habit: PatientEatingHabitCreate,
        sleep_habit: PatientSleepHabitCreate,
        food_allergies: Optional[List[PatientFoodAllergyCreate]] = None,
        *,
        postgres_session: AsyncSession,
    ):
        try:
            patient_profile = await self.fetch_patient_profile(
                patient_id, detailed=True, postgres_session=postgres_session
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

            postgres_session.add(patient_profile)
            await postgres_session.commit()
            await postgres_session.refresh(patient_profile)

            updated_patient = await self.fetch_patient_profile(
                patient_id, detailed=True, postgres_session=postgres_session
            )
            return updated_patient

        except IntegrityError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Integrity Error",
                detail=str(e),
            )
        except SQLAlchemyError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    @with_postgres_session
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
        *,
        postgres_session: AsyncSession,
    ) -> PatientModel:
        try:
            patient_profile = await self.fetch_patient_profile(
                patient_id, detailed=True, postgres_session=postgres_session
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

            postgres_session.add(patient_profile)
            await postgres_session.commit()
            await postgres_session.refresh(patient_profile)

            updated_patient = await self.fetch_patient_profile(
                patient_id, detailed=True, postgres_session=postgres_session
            )

            return updated_patient

        except IntegrityError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Integrity Error",
                detail=str(e),
            )
        except SQLAlchemyError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    @with_postgres_session
    async def delete_patient_profile(
        self,
        patient_id: str,
        delete_chats: bool = False,
        *,
        postgres_session: AsyncSession,
    ) -> None:
        try:
            patient = await self.fetch_patient_profile(
                patient_id, postgres_session=postgres_session
            )

            if delete_chats:
                await self.chat_management_service.delete_all_chats(
                    user_id=str(patient.patient_id),
                )

            await postgres_session.delete(patient)
            await postgres_session.commit()

        except SQLAlchemyError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    @with_postgres_session
    async def assign_care_providers_to_patient(
        self,
        patient_id: str,
        care_provider_ids: list[str],
        health_facility_id: str,
        *,
        postgres_session: AsyncSession,
    ) -> PatientModel:
        try:
            patient = await self.fetch_patient_profile(
                patient_id, postgres_session=postgres_session
            )

            print(
                "==> patient.health_facility_id: ", patient.health_facility_id
            )
            # Auto-assign health facility if not already assigned
            if not str(patient.health_facility_id):
                patient.health_facility_id = health_facility_id
            elif str(patient.health_facility_id) != health_facility_id:
                raise_http_exception(400, "Patient is in a different facility")

            # Fetch all care providers in batch (scoped to same facility)
            stmt = select(CareProviderModel).where(
                CareProviderModel.care_provider_id.in_(care_provider_ids),
                CareProviderModel.health_facility_id == health_facility_id,
            )
            result = await postgres_session.execute(stmt)
            fetched_care_providers = result.scalars().all()

            fetched_ids = {
                str(cp.care_provider_id) for cp in fetched_care_providers
            }
            missing_ids = set(care_provider_ids) - fetched_ids
            if missing_ids:
                raise_http_exception(
                    404,
                    message=f"Care provider(s) not found or not in your health facility: {', '.join(missing_ids)}",
                )

            # Track which ones are newly added for chat creation
            newly_added_providers = []

            for cp in fetched_care_providers:
                if cp not in patient.care_providers:
                    patient.care_providers.append(cp)
                    newly_added_providers.append(cp)

            if not newly_added_providers:
                raise_http_exception(
                    400, "All care providers already assigned."
                )

            # Ensure changes are flushed before creating chats
            await postgres_session.flush()

            # Create chats and notifications
            for cp in newly_added_providers:
                await self.chat_management_service.create_chat_relationships(
                    str(patient.patient_id), str(cp.care_provider_id)
                )

            await postgres_session.commit()
            await postgres_session.refresh(patient)
            return patient

        except ChatCreationError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=500,
                message="Chat creation failed",
                detail=str(e),
            )

        except SQLAlchemyError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=500,
                message="Database error during care provider assignment",
                detail=str(e),
            )

    @with_postgres_session
    async def assign_care_provider_to_patients(
        self,
        care_provider_id: str,
        patient_ids: list[str],
        health_facility_id: str,
        *,
        postgres_session: AsyncSession,
    ) -> list[PatientModel]:
        try:
            # Fetch care provider
            care_provider = (
                await self.care_provider_service.fetch_care_provider(
                    care_provider_id
                )
            )
            care_provider = await postgres_session.merge(care_provider)

            if str(care_provider.health_facility_id) != health_facility_id:
                raise_http_exception(
                    400, "Care provider is in a different facility"
                )

            # Fetch all patients in batch
            patient_map = await self.fetch_patient_profiles(
                patient_ids, postgres_session=postgres_session
            )

            assigned_patients = []
            for patient_id in patient_ids:
                patient = patient_map.get(patient_id)
                if not patient:
                    continue

                # Facility checks
                if (
                    patient.health_facility_id
                    and str(patient.health_facility_id) != health_facility_id
                ):
                    continue

                # Auto-assign facility if not already assigned
                if not patient.health_facility_id:
                    patient.health_facility_id = health_facility_id

                if care_provider not in patient.care_providers:
                    patient.care_providers.append(care_provider)
                    await self.chat_management_service.create_chat_relationships(
                        str(patient.patient_id),
                        str(care_provider.care_provider_id),
                    )

                    assigned_patients.append(patient)

            if not assigned_patients:
                raise_http_exception(
                    400,
                    "Care provider was already assigned to all patients or invalid patients",
                )

            await postgres_session.commit()

            return assigned_patients

        except ChatCreationError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=500,
                message="Chat creation failed",
                detail=str(e),
            )

        except SQLAlchemyError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=500,
                message="Database error during bulk patient assignment",
                detail=str(e),
            )

    @with_postgres_session
    async def remove_care_providers_from_patient(
        self,
        patient_id: str,
        care_provider_ids: list[str],
        health_facility_id: str,
        *,
        postgres_session: AsyncSession,
    ) -> None:
        try:
            patient = await self.fetch_patient_profile(
                patient_id, detailed=True, postgres_session=postgres_session
            )

            # Ensure patient is in the same facility
            if str(patient.health_facility_id) != health_facility_id:
                raise_http_exception(400, "Patient is in a different facility")

            if not patient.care_providers:
                raise_http_exception(
                    400, "Patient has no assigned care providers"
                )

            # Fetch care providers in batch
            stmt = select(CareProviderModel).where(
                CareProviderModel.care_provider_id.in_(care_provider_ids),
                CareProviderModel.health_facility_id == health_facility_id,
            )
            result = await postgres_session.execute(stmt)
            care_providers_to_remove = result.scalars().all()

            if not care_providers_to_remove:
                raise_http_exception(404, "No matching care providers found")

            removed_ids = []

            for cp in care_providers_to_remove:
                if cp in patient.care_providers:
                    patient.care_providers.remove(cp)
                    removed_ids.append(str(cp.care_provider_id))

            if not removed_ids:
                raise_http_exception(
                    400,
                    "None of the care providers were assigned to the patient",
                )

            postgres_session.add(patient)
            await postgres_session.commit()

            # Disable chats and send notifications
            for cp_id in removed_ids:
                await self.chat_management_service.disable_direct_chat(
                    patient_id=patient_id,
                    care_provider_id=cp_id,
                )
                await self.chat_notification_service.notify_participants(
                    message_key=EmitMessageKeyEnum.CHAT_LIST_UPDATED.value,
                    user_id=cp_id,
                )

            await self.chat_notification_service.notify_participants(
                message_key=EmitMessageKeyEnum.CHAT_LIST_UPDATED.value,
                user_id=patient_id,
            )

        except SQLAlchemyError as e:
            await postgres_session.rollback()
            raise_http_exception(500, "Database Error", detail=str(e))

    @with_postgres_session
    async def remove_care_provider_from_patients(
        self,
        care_provider_id: str,
        patient_ids: list[str],
        health_facility_id: str,
        *,
        postgres_session: AsyncSession,
    ) -> list[str]:
        try:
            # Fetch care provider
            care_provider = (
                await self.care_provider_service.fetch_care_provider(
                    care_provider_id
                )
            )
            care_provider = await postgres_session.merge(care_provider)

            if str(care_provider.health_facility_id) != health_facility_id:
                raise_http_exception(
                    400, "Care provider is in a different facility"
                )

            # Fetch patients in batch
            patient_map = await self.fetch_patient_profiles(
                patient_ids, postgres_session=postgres_session
            )

            removed_patient_ids = []

            for patient_id in patient_ids:
                patient = patient_map.get(patient_id)
                if not patient:
                    continue

                # Ensure same facility
                if str(patient.health_facility_id) != health_facility_id:
                    continue

                if care_provider in patient.care_providers:
                    patient.care_providers.remove(care_provider)
                    removed_patient_ids.append(patient_id)

            if not removed_patient_ids:
                raise_http_exception(
                    400,
                    "Care provider was not assigned to any of the specified patients",
                )

            await postgres_session.commit()

            # Disable chat + notify all
            for pid in removed_patient_ids:
                await self.chat_management_service.disable_direct_chat(
                    patient_id=pid,
                    care_provider_id=care_provider_id,
                )
                await self.chat_notification_service.notify_participants(
                    message_key=EmitMessageKeyEnum.CHAT_LIST_UPDATED.value,
                    user_id=pid,
                )

            await self.chat_notification_service.notify_participants(
                message_key=EmitMessageKeyEnum.CHAT_LIST_UPDATED.value,
                user_id=care_provider_id,
            )

            return removed_patient_ids

        except SQLAlchemyError as e:
            await postgres_session.rollback()
            raise_http_exception(500, "Database Error", detail=str(e))

    @with_postgres_session
    async def add_care_provider_by_code(
        self,
        patient_id: str,
        care_provider_code: str,
        *,
        postgres_session: AsyncSession,
    ) -> CareProviderModel:
        try:
            # Fetch care provider by code
            stmt = select(CareProviderModel).where(
                CareProviderModel.code == care_provider_code
            )
            care_provider = (
                (await postgres_session.execute(stmt)).scalars().first()
            )

            if not care_provider:
                raise_http_exception(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message="Invalid care provider code.",
                )

            # Fetch patient with full details
            patient = await self.fetch_patient_profile(
                patient_id, detailed=True, postgres_session=postgres_session
            )

            if care_provider in patient.care_providers:
                raise_http_exception(
                    status.HTTP_400_BAD_REQUEST,
                    "Care provider is already added.",
                )

            # Link care provider and assign facility
            patient.care_providers.append(care_provider)
            patient.health_facility_id = care_provider.health_facility_id
            postgres_session.add(patient)

            # Create chats and notifications
            await self.chat_management_service.create_chat_relationships(
                str(patient.patient_id),
                str(care_provider.care_provider_id),
            )

            await postgres_session.commit()
            await postgres_session.refresh(patient)

            return care_provider

        except ChatCreationError as e:
            await postgres_session.rollback()
            raise_http_exception(500, "Chat creation failed", detail=str(e))

        except SQLAlchemyError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    @with_postgres_session
    async def check_patient_exists(
        self, patient_id: str, *, postgres_session: AsyncSession
    ) -> bool:
        try:
            stmt = select(
                exists().where(PatientModel.patient_id == patient_id)
            )
            exists_result = await postgres_session.scalar(stmt)

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

    @with_postgres_session
    async def _upsert_multiple_entities(
        self,
        existing_entities,
        new_data_list,
        model,
        foreign_key_name,
        foreign_key_value,
        *,
        postgres_session: AsyncSession,
    ):
        """Helper method to delete existing entities and upsert multiple new entities."""

        # Delete existing entities
        for entity in existing_entities:
            await postgres_session.delete(entity)

        # Create new entities
        new_entities = [
            model(**data.dict(), **{foreign_key_name: foreign_key_value})
            for data in new_data_list
        ]

        # Add new entities to the session
        postgres_session.add_all(new_entities)

        return new_entities

    def _mark_profile_section_complete(
        self, profile_completion, section: str
    ) -> bool:
        if not profile_completion[section]["is_complete"]:
            profile_completion[section]["is_complete"] = True
            return True
        return False
