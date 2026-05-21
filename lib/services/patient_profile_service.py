import uuid
from typing import Dict, List, Optional

from fastapi import HTTPException, status
from sqlalchemy import distinct, exists, func, or_
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
from lib.models.patient_reproductive_health import (
    PatientReproductiveHealth as PatientReproductiveHealthModel,
)
from lib.models.patient_diet_plan import PatientDietPlan as PatientDietPlanModel
from lib.models.patient_fitness_plan import PatientFitnessPlan as PatientFitnessPlanModel
from lib.models.patient_sleep_habit import (
    PatientSleepHabit as PatientSleepHabitModel,
)
from lib.models.patient_smoking_habit import (
    PatientSmokingHabit as PatientSmokingHabitModel,
)
from lib.schemas.patient import (
    CorePatientProfile,
    PatientCreate,
)
from lib.schemas.patient import PatientUpdate
from lib.schemas.patient_alcohol_consumption import (
    PatientAlcoholConsumptionCreate,
)
from lib.models.patient_package_assignment import (
    PatientPackageAssignment as PatientPackageAssignmentModel,
)
from lib.schemas.patient_daily_activity import PatientDailyActivityCreate
from lib.schemas.patient_diabetic_history import PatientDiabeticHistoryCreate
from lib.schemas.patient_drug_allergy import PatientDrugAllergyCreate
from lib.schemas.patient_eating_habit import PatientEatingHabitCreate
from lib.schemas.patient_family_diabetic_history import (
    PatientFamilyDiabeticHistoryCreate,
)
from lib.schemas.patient_food_allergy import PatientFoodAllergyCreate
from lib.schemas.patient_meal_timing import PatientMealTimingCreate
from lib.schemas.patient_medical_history import PatientMedicalHistoryCreate
from lib.schemas.patient_sleep_habit import PatientSleepHabitCreate
from lib.schemas.patient_smoking_habit import PatientSmokingHabitCreate
from lib.schemas.patient_onboarding import (
    PatientOnboardingRequest,
    PatientProfileUpdate,
)
from lib.services.care_provider_profile_service import (
    CareProviderProfileService,
)
from lib.services.chat.chat_exceptions import ChatCreationError
from lib.services.chat.chat_management_service import ChatManagementService
from lib.services.chat.chat_notification_service import ChatNotificationService
from lib.services.vector import PatientProfileVectorService
from lib.utils.http_exceptions import raise_http_exception
from lib.utils.postgres_session_decorator import with_postgres_session
from lib.workers.tasks.profile.enqueue import (
    enqueue_generate_profile_vector_sync,
)


class PatientProfileService:
    def __init__(
        self,
        postgres_store: PostgresStore,
        care_provider_service: CareProviderProfileService,
        chat_notification_service: ChatNotificationService,
        chat_management_service: ChatManagementService,
        profile_vector_service: PatientProfileVectorService,
    ):
        self.postgres_store = postgres_store
        self.care_provider_service = care_provider_service
        self.chat_notification_service = chat_notification_service
        self.chat_management_service = chat_management_service
        self.profile_vector_service = profile_vector_service

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
                    joinedload(PatientModel.package_assignments).options(
                        selectinload(PatientPackageAssignmentModel.package)
                    ),
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
                    selectinload(PatientModel.diet_plans),
                    selectinload(PatientModel.fitness_plans),
                    selectinload(PatientModel.diabetic_history),
                    selectinload(PatientModel.reproductive_health),
                    selectinload(PatientModel.family_diabetic_histories),
                    selectinload(PatientModel.medical_histories),
                )

            if include_health_data:
                stmt = stmt.options(
                    selectinload(PatientModel.smbgs),
                )

            if other_related_data:
                stmt = stmt.options(
                    selectinload(PatientModel.permissions),
                    joinedload(PatientModel.connected_apps).joinedload(
                        PatientConnectedApp.libreview
                    ),
                    joinedload(PatientModel.connected_apps).joinedload(
                        PatientConnectedApp.sinocare
                    ),
                    joinedload(PatientModel.connected_apps).joinedload(
                        PatientConnectedApp.other_app
                    ),
                    selectinload(PatientModel.weight_loss_enrollment),
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
    async def fetch_patients(
        self,
        health_facility_id: Optional[str] = None,
        care_provider_id: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
        *,
        postgres_session: AsyncSession,
    ) -> List[PatientModel]:
        try:
            stmt = select(PatientModel).options(
                selectinload(PatientModel.health_facility),
                selectinload(PatientModel.care_providers),
                selectinload(PatientModel.package_assignments).options(
                    selectinload(PatientPackageAssignmentModel.package)
                ),
            )

            if care_provider_id:
                stmt = stmt.join(PatientModel.care_providers).where(
                    CareProviderModel.care_provider_id == care_provider_id
                )

            if health_facility_id:
                stmt = stmt.where(PatientModel.health_facility_id == health_facility_id)

            if offset:
                stmt = stmt.offset(offset)

            if limit:
                stmt = stmt.limit(limit)

            result = await postgres_session.execute(stmt)
            patients = result.scalars().all()

            return list(patients)

        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    @with_postgres_session
    async def count_patients(
        self,
        health_facility_id: Optional[str] = None,
        care_provider_id: Optional[str] = None,
        *,
        postgres_session: AsyncSession,
    ) -> int:
        try:
            stmt = select(func.count(distinct(PatientModel.patient_id)))

            if care_provider_id:
                stmt = stmt.join(PatientModel.care_providers).where(
                    CareProviderModel.care_provider_id == care_provider_id
                )

            if health_facility_id:
                stmt = stmt.where(PatientModel.health_facility_id == health_facility_id)

            result = await postgres_session.execute(stmt)
            count = result.scalar() or 0

            return count

        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    @with_postgres_session
    async def fetch_patient_profiles(
        self,
        patient_ids: List[str],
        detailed: bool = False,
        *,
        postgres_session: AsyncSession,
    ) -> Dict[str, PatientModel]:
        try:
            stmt = (
                select(PatientModel)
                .where(PatientModel.patient_id.in_(patient_ids))
                .options(
                    selectinload(PatientModel.care_providers),
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
                    selectinload(PatientModel.diet_plans),
                    selectinload(PatientModel.fitness_plans),
                    selectinload(PatientModel.diabetic_history),
                    selectinload(PatientModel.reproductive_health),
                    selectinload(PatientModel.family_diabetic_histories),
                    selectinload(PatientModel.medical_histories),
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

            for key, value in patient_data.model_dump(exclude_unset=True).items():
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

            profile_data = CorePatientProfile.from_orm(updated_patient).model_dump(
                mode="json"
            )
            enqueue_generate_profile_vector_sync(patient_id, profile_data)
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

            patient_profile.food_allergies = await self._upsert_multiple_entities(
                patient_profile.food_allergies,
                food_allergies or [],
                PatientFoodAllergyModel,
                "patient_id",
                patient_id,
                postgres_session=postgres_session,
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
                    postgres_session=postgres_session,
                )
            )

            patient_profile.eating_habit.diet_preferences = self._upsert_single_entity(
                patient_profile.eating_habit.diet_preferences,
                eating_habit.diet_preferences,
                PatientDietPreferenceModel,
                "eating_habit_id",
                patient_profile.eating_habit.eating_habit_id,
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

            profile_data = CorePatientProfile.from_orm(updated_patient).model_dump(
                mode="json"
            )
            enqueue_generate_profile_vector_sync(patient_id, profile_data)
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

            patient_profile.drug_allergies = await self._upsert_multiple_entities(
                patient_profile.drug_allergies,
                drug_allergies or [],
                PatientDrugAllergyModel,
                "patient_id",
                patient_id,
                postgres_session=postgres_session,
            )

            patient_profile.family_diabetic_histories = (
                await self._upsert_multiple_entities(
                    patient_profile.family_diabetic_histories,
                    family_diabetic_histories or [],
                    PatientFamilyDiabeticHistoryModel,
                    "patient_id",
                    patient_id,
                    postgres_session=postgres_session,
                )
            )

            patient_profile.medical_histories = await self._upsert_multiple_entities(
                patient_profile.medical_histories,
                medical_histories or [],
                PatientMedicalHistoryModel,
                "patient_id",
                patient_id,
                postgres_session=postgres_session,
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

            profile_data = CorePatientProfile.from_orm(updated_patient).model_dump(
                mode="json"
            )
            enqueue_generate_profile_vector_sync(patient_id, profile_data)
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
    async def update_patient_profile(
        self,
        patient_id: str,
        data: PatientProfileUpdate,
        *,
        postgres_session: AsyncSession,
    ) -> PatientModel:
        """Partial profile update — used by the chat-style onboarding flow.

        Only fields the client explicitly sent are written. Top-level lists
        (food_allergies, drug_allergies, family_diabetic_histories,
        medical_histories) replace the whole list when present.

        Recomputes profile_completion sections based on field presence —
        no separate finalize call needed.
        """
        try:
            patient = await self.fetch_patient_profile(
                patient_id, detailed=True, postgres_session=postgres_session
            )

            sent = data.model_dump(exclude_unset=True)

            # ── Identity & body scalars ─────────────────────────────────
            for field in (
                "first_name", "last_name", "email", "gender", "dob",
                "profile_picture", "occupation",
                "height_cm", "weight_kg", "waist_cm", "hip_cm",
            ):
                if field in sent:
                    setattr(patient, field, sent[field])
            if "timezone" in sent:
                patient.timezone = sent["timezone"]
                patient.locale = sent["timezone"]  # legacy dual-write
            # Legacy body field dual-writes
            if "height_cm" in sent:
                patient.height = sent["height_cm"]
            if "weight_kg" in sent:
                patient.weight = sent["weight_kg"]
            if "waist_cm" in sent:
                patient.waist = sent["waist_cm"]

            # ── Section partial-merges ──────────────────────────────────
            if data.daily_activity is not None:
                self._merge_daily_activity(
                    patient, data.daily_activity, patient_id
                )
            if data.smoking_habit is not None:
                self._merge_smoking_habit(
                    patient, data.smoking_habit, patient_id
                )
            if data.alcohol_consumption is not None:
                self._merge_alcohol_consumption(
                    patient, data.alcohol_consumption, patient_id
                )
            if data.sleep_habit is not None:
                self._merge_sleep_habit(
                    patient, data.sleep_habit, patient_id
                )
            if data.eating_habit is not None:
                await self._merge_eating_habit(
                    patient,
                    data.eating_habit,
                    patient_id,
                    postgres_session=postgres_session,
                )
            if data.diabetic_history is not None:
                self._merge_diabetic_history(
                    patient, data.diabetic_history, patient_id
                )
            # reproductive_health supports explicit-null to clear the row
            # (used when gender changes from FEMALE to non-FEMALE)
            if "reproductive_health" in sent:
                if data.reproductive_health is None:
                    if patient.reproductive_health is not None:
                        await postgres_session.delete(patient.reproductive_health)
                        patient.reproductive_health = None
                    # Also clear legacy pregnancy fields on diabetic_history
                    if patient.diabetic_history is not None:
                        patient.diabetic_history.is_pregnant = None
                        patient.diabetic_history.pregnancy_weeks = None
                else:
                    self._merge_reproductive_health(
                        patient, data.reproductive_health, patient_id
                    )

            # ── Lists: replace whole when present ───────────────────────
            if data.food_allergies is not None:
                patient.food_allergies = await self._upsert_multiple_entities(
                    patient.food_allergies,
                    [
                        PatientFoodAllergyCreate(
                            allergy_name=fa.name_other or fa.name,
                            name=fa.name,
                            name_other=fa.name_other,
                            severity=fa.severity,
                        )
                        for fa in data.food_allergies
                    ],
                    PatientFoodAllergyModel,
                    "patient_id",
                    patient_id,
                    postgres_session=postgres_session,
                )
            if data.drug_allergies is not None:
                patient.drug_allergies = await self._upsert_multiple_entities(
                    patient.drug_allergies,
                    [
                        PatientDrugAllergyCreate(
                            allergy_name=da.name_other or da.name,
                            name=da.name,
                            name_other=da.name_other,
                            reaction=da.reaction,
                        )
                        for da in data.drug_allergies
                    ],
                    PatientDrugAllergyModel,
                    "patient_id",
                    patient_id,
                    postgres_session=postgres_session,
                )
            if data.family_diabetic_histories is not None:
                patient.family_diabetic_histories = (
                    await self._upsert_multiple_entities(
                        patient.family_diabetic_histories,
                        [
                            PatientFamilyDiabeticHistoryCreate(
                                family_member=fdh.family_member,
                                type_of_diabetes=fdh.type_of_diabetes,
                                years_with_diabetes=fdh.years_with_diabetes,
                            )
                            for fdh in data.family_diabetic_histories
                        ],
                        PatientFamilyDiabeticHistoryModel,
                        "patient_id",
                        patient_id,
                        postgres_session=postgres_session,
                    )
                )
            if data.medical_histories is not None:
                patient.medical_histories = await self._upsert_multiple_entities(
                    patient.medical_histories,
                    [
                        PatientMedicalHistoryCreate(
                            condition=mh.condition,
                            condition_other=mh.condition_other,
                            status=mh.status,
                            duration_years=mh.duration_years,
                            started_at=mh.started_at,
                            details=mh.details,
                        )
                        for mh in data.medical_histories
                    ],
                    PatientMedicalHistoryModel,
                    "patient_id",
                    patient_id,
                    postgres_session=postgres_session,
                )

            self._recompute_profile_completion(patient)

            postgres_session.add(patient)
            await postgres_session.commit()
            await postgres_session.refresh(patient)

            updated_patient = await self.fetch_patient_profile(
                patient_id, detailed=True, postgres_session=postgres_session
            )
            profile_data = CorePatientProfile.from_orm(updated_patient).model_dump(
                mode="json"
            )
            enqueue_generate_profile_vector_sync(patient_id, profile_data)
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

    # ─── partial-merge helpers ──────────────────────────────────────────────

    @staticmethod
    def _merge_daily_activity(patient, partial, patient_id: str) -> None:
        fields = partial.model_dump(exclude_unset=True)
        if not fields:
            return
        entity = patient.daily_activity or PatientDailyActivityModel(
            patient_id=patient_id
        )
        for k, v in fields.items():
            setattr(entity, k, v)
        patient.daily_activity = entity

    @staticmethod
    def _merge_smoking_habit(patient, partial, patient_id: str) -> None:
        fields = partial.model_dump(exclude_unset=True)
        if not fields:
            return
        entity = patient.smoking_habit or PatientSmokingHabitModel(
            patient_id=patient_id
        )
        for k, v in fields.items():
            if k == "smoke_type":
                entity.smoke_type = list(v) if v else None
            else:
                setattr(entity, k, v)
        if "status" in fields:
            entity.smoke_status = fields["status"] == "CURRENT"  # legacy
        patient.smoking_habit = entity

    @staticmethod
    def _merge_alcohol_consumption(patient, partial, patient_id: str) -> None:
        fields = partial.model_dump(exclude_unset=True)
        if not fields:
            return
        entity = patient.alcohol_consumption or PatientAlcoholConsumptionModel(
            patient_id=patient_id
        )
        for k, v in fields.items():
            if k == "type_of_alcohol":
                entity.type_of_alcohol = list(v) if v else None
            else:
                setattr(entity, k, v)
        if "status" in fields:
            entity.consume_alcohol = fields["status"] != "NEVER"  # legacy
        if "drinks_per_session" in fields:
            entity.quantity = (
                str(fields["drinks_per_session"])
                if fields["drinks_per_session"] is not None
                else None
            )  # legacy
        patient.alcohol_consumption = entity

    @staticmethod
    def _merge_sleep_habit(patient, partial, patient_id: str) -> None:
        fields = partial.model_dump(exclude_unset=True)
        if not fields:
            return
        entity = patient.sleep_habit or PatientSleepHabitModel(
            patient_id=patient_id
        )
        for k, v in fields.items():
            setattr(entity, k, v)
        if "average_sleep_hours" in fields:
            entity.average_sleep_duration = (
                str(fields["average_sleep_hours"])
                if fields["average_sleep_hours"] is not None
                else None
            )  # legacy
        patient.sleep_habit = entity

    @staticmethod
    def _merge_diabetic_history(patient, partial, patient_id: str) -> None:
        fields = partial.model_dump(exclude_unset=True)
        if not fields:
            return
        entity = patient.diabetic_history or PatientDiabeticHistoryModel(
            patient_id=patient_id
        )
        for k, v in fields.items():
            setattr(entity, k, v)
        patient.diabetic_history = entity

    @staticmethod
    def _merge_reproductive_health(patient, partial, patient_id: str) -> None:
        fields = partial.model_dump(exclude_unset=True)
        if not fields:
            return
        entity = patient.reproductive_health or PatientReproductiveHealthModel(
            patient_id=patient_id
        )
        for k, v in fields.items():
            setattr(entity, k, v)
        patient.reproductive_health = entity
        # Legacy dual-write: pregnancy fields still live on diabetic_history
        diabetic = patient.diabetic_history or PatientDiabeticHistoryModel(
            patient_id=patient_id
        )
        if "is_pregnant" in fields:
            diabetic.is_pregnant = fields["is_pregnant"]
        if "pregnancy_weeks" in fields:
            diabetic.pregnancy_weeks = fields["pregnancy_weeks"]
        patient.diabetic_history = diabetic

    async def _merge_eating_habit(
        self, patient, partial, patient_id: str, *, postgres_session
    ) -> None:
        fields = partial.model_dump(exclude_unset=True)
        if not fields:
            return

        # Capture existing relations BEFORE any mutation so we don't lazy-load
        # after a flush in async context (greenlet_spawn error).
        existing_habit = patient.eating_habit
        existing_meal_timings = (
            list(existing_habit.meal_timings) if existing_habit else []
        )
        existing_pref = existing_habit.diet_preferences if existing_habit else None

        # New habits get an explicit eating_habit_id so we never need to flush
        # mid-method to populate the FK target for meal_timings / diet_preferences.
        habit = existing_habit or PatientEatingHabitModel(
            patient_id=patient_id,
            eating_habit_id=uuid.uuid4(),
        )
        for k in ("meals_per_day", "snacks_count", "diet_preferences_detail"):
            if k in fields:
                setattr(habit, k, fields[k])
        if "cuisine_preferences" in fields:
            habit.cuisine_preferences = list(fields["cuisine_preferences"]) or None
        if "diet_preferences" in fields:
            habit.dietary_preferences = list(fields["diet_preferences"]) or None
        patient.eating_habit = habit

        # Lists within eating_habit — replace whole when present
        if "meal_timings" in fields and partial.meal_timings is not None:
            habit.meal_timings = await self._upsert_multiple_entities(
                existing_meal_timings,
                [
                    PatientMealTimingCreate(
                        meal_type=mt.meal_type,
                        time=mt.time.strftime("%H:%M"),
                    )
                    for mt in partial.meal_timings
                ],
                PatientMealTimingModel,
                "eating_habit_id",
                habit.eating_habit_id,
                postgres_session=postgres_session,
            )

        # Legacy dual-write: PatientDietPreference table holds one row.
        if "diet_preferences" in fields and partial.diet_preferences:
            pref = existing_pref or PatientDietPreferenceModel(
                eating_habit_id=habit.eating_habit_id,
            )
            pref.preference = partial.diet_preferences[0]
            if "diet_preferences_detail" in fields:
                pref.detail = fields["diet_preferences_detail"]
            habit.diet_preferences = pref

    @staticmethod
    def _recompute_profile_completion(patient) -> None:
        pc = patient.profile_completion or {}
        sections = {
            "basic": bool(
                patient.first_name
                and patient.gender
                and patient.dob
                and (patient.height_cm or patient.height)
                and (patient.weight_kg or patient.weight)
            ),
            "lifestyle": bool(
                patient.daily_activity
                and patient.alcohol_consumption
                and patient.smoking_habit
                and patient.sleep_habit
                and patient.eating_habit
            ),
            "medical_history": bool(patient.diabetic_history),
        }
        changed = False
        for section, is_complete in sections.items():
            if section not in pc:
                pc[section] = {"is_complete": False, "is_mandatory": True}
            if pc[section].get("is_complete") != is_complete:
                pc[section]["is_complete"] = is_complete
                changed = True
        if changed:
            patient.profile_completion = pc
            flag_modified(patient, "profile_completion")

    @with_postgres_session
    async def complete_onboarding(
        self,
        patient_id: str,
        data: PatientOnboardingRequest,
        *,
        postgres_session: AsyncSession,
    ) -> PatientModel:
        """Single-transaction onboarding: identity + lifestyle + medical history.

        Dual-writes new clean columns (status enums, drinks_per_session,
        average_sleep_hours, timezone) alongside legacy columns (smoke_status
        bool, quantity str, average_sleep_duration str, locale) during soak.
        """
        try:
            patient = await self.fetch_patient_profile(
                patient_id, detailed=True, postgres_session=postgres_session
            )

            self._apply_identity_and_body(patient, data)
            self._apply_daily_activity(patient, data.daily_activity, patient_id)
            self._apply_smoking_habit(patient, data.smoking_habit, patient_id)
            self._apply_alcohol_consumption(
                patient, data.alcohol_consumption, patient_id
            )
            self._apply_sleep_habit(patient, data.sleep_habit, patient_id)
            await self._apply_eating_habit(
                patient,
                data.eating_habit,
                patient_id,
                postgres_session=postgres_session,
            )
            patient.food_allergies = await self._upsert_multiple_entities(
                patient.food_allergies,
                [
                    PatientFoodAllergyCreate(
                        allergy_name=fa.name_other or fa.name,  # legacy
                        name=fa.name,
                        name_other=fa.name_other,
                        severity=fa.severity,
                    )
                    for fa in data.food_allergies
                ],
                PatientFoodAllergyModel,
                "patient_id",
                patient_id,
                postgres_session=postgres_session,
            )
            self._apply_diabetic_history(
                patient,
                data.diabetic_history,
                data.reproductive_health,
                patient_id,
            )
            self._apply_reproductive_health(
                patient, data.reproductive_health, patient_id
            )
            patient.drug_allergies = await self._upsert_multiple_entities(
                patient.drug_allergies,
                [
                    PatientDrugAllergyCreate(
                        allergy_name=da.name_other or da.name,  # legacy
                        name=da.name,
                        name_other=da.name_other,
                        reaction=da.reaction,
                    )
                    for da in data.drug_allergies
                ],
                PatientDrugAllergyModel,
                "patient_id",
                patient_id,
                postgres_session=postgres_session,
            )
            patient.family_diabetic_histories = (
                await self._upsert_multiple_entities(
                    patient.family_diabetic_histories,
                    [
                        PatientFamilyDiabeticHistoryCreate(
                            family_member=fdh.family_member,
                            type_of_diabetes=fdh.type_of_diabetes,
                            years_with_diabetes=fdh.years_with_diabetes,
                        )
                        for fdh in data.family_diabetic_histories
                    ],
                    PatientFamilyDiabeticHistoryModel,
                    "patient_id",
                    patient_id,
                    postgres_session=postgres_session,
                )
            )
            patient.medical_histories = await self._upsert_multiple_entities(
                patient.medical_histories,
                [
                    PatientMedicalHistoryCreate(
                        condition=mh.condition,
                        condition_other=mh.condition_other,
                        status=mh.status,
                        duration_years=mh.duration_years,
                        started_at=mh.started_at,
                        details=mh.details,
                    )
                    for mh in data.medical_histories
                ],
                PatientMedicalHistoryModel,
                "patient_id",
                patient_id,
                postgres_session=postgres_session,
            )

            for section in ("basic", "lifestyle", "medical_history"):
                if self._mark_profile_section_complete(
                    patient.profile_completion, section
                ):
                    flag_modified(patient, "profile_completion")

            postgres_session.add(patient)
            await postgres_session.commit()
            await postgres_session.refresh(patient)

            await self.chat_notification_service.notify_participants(
                message_key=EmitMessageKeyEnum.CHAT_LIST_UPDATED.value,
                user_id=patient_id,
            )

            updated_patient = await self.fetch_patient_profile(
                patient_id, detailed=True, postgres_session=postgres_session
            )
            profile_data = CorePatientProfile.from_orm(updated_patient).model_dump(
                mode="json"
            )
            enqueue_generate_profile_vector_sync(patient_id, profile_data)
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

    # ─── onboarding section appliers ────────────────────────────────────────

    @staticmethod
    def _apply_identity_and_body(
        patient: PatientModel, data: PatientOnboardingRequest
    ) -> None:
        patient.first_name = data.first_name
        if data.last_name is not None:
            patient.last_name = data.last_name
        if data.email is not None:
            patient.email = data.email
        patient.gender = data.gender
        patient.dob = data.dob
        if data.profile_picture is not None:
            patient.profile_picture = data.profile_picture
        patient.timezone = data.timezone
        patient.locale = data.timezone  # dual-write during soak
        if data.occupation is not None:
            patient.occupation = data.occupation
        patient.height_cm = data.height_cm
        patient.weight_kg = data.weight_kg
        patient.height = data.height_cm  # legacy dual-write
        patient.weight = data.weight_kg  # legacy dual-write
        if data.waist_cm is not None:
            patient.waist_cm = data.waist_cm
            patient.waist = data.waist_cm  # legacy dual-write
        if data.hip_cm is not None:
            patient.hip_cm = data.hip_cm

    @staticmethod
    def _apply_daily_activity(patient, section, patient_id: str) -> None:
        if patient.daily_activity:
            patient.daily_activity.activity_level = section.activity_level
        else:
            patient.daily_activity = PatientDailyActivityModel(
                patient_id=patient_id,
                activity_level=section.activity_level,
            )

    @staticmethod
    def _apply_smoking_habit(patient, section, patient_id: str) -> None:
        entity = patient.smoking_habit or PatientSmokingHabitModel(
            patient_id=patient_id
        )
        entity.status = section.status
        entity.smoke_status = section.status == "CURRENT"  # legacy dual-write
        entity.smoke_type = list(section.smoke_type) or None
        entity.cigarettes_per_day = section.cigarettes_per_day
        entity.years_of_smoking = section.years_of_smoking
        entity.quit_years_ago = section.quit_years_ago
        patient.smoking_habit = entity

    @staticmethod
    def _apply_alcohol_consumption(patient, section, patient_id: str) -> None:
        entity = patient.alcohol_consumption or PatientAlcoholConsumptionModel(
            patient_id=patient_id
        )
        entity.status = section.status
        entity.consume_alcohol = section.status != "NEVER"  # legacy dual-write
        entity.frequency = section.frequency
        entity.drinks_per_session = section.drinks_per_session
        entity.quantity = (
            str(section.drinks_per_session)
            if section.drinks_per_session is not None
            else None
        )  # legacy dual-write
        entity.type_of_alcohol = list(section.type_of_alcohol) or None
        entity.quit_years_ago = section.quit_years_ago
        patient.alcohol_consumption = entity

    @staticmethod
    def _apply_sleep_habit(patient, section, patient_id: str) -> None:
        entity = patient.sleep_habit or PatientSleepHabitModel(
            patient_id=patient_id
        )
        entity.sleep_quality = section.sleep_quality
        entity.average_sleep_hours = section.average_sleep_hours
        entity.average_sleep_duration = (
            str(section.average_sleep_hours)
            if section.average_sleep_hours is not None
            else None
        )  # legacy dual-write
        entity.bed_time = section.bed_time
        entity.wake_up_time = section.wake_up_time
        entity.wake_up_fresh = section.wake_up_fresh
        entity.drowsy_day = section.drowsy_day
        entity.snores = section.snores
        patient.sleep_habit = entity

    @staticmethod
    def _apply_diabetic_history(
        patient, section, reproductive, patient_id: str
    ) -> None:
        entity = patient.diabetic_history or PatientDiabeticHistoryModel(
            patient_id=patient_id
        )
        entity.type_of_diabetes = section.type_of_diabetes
        entity.years_with_diabetes = section.years_with_diabetes
        entity.diagnosed_at = section.diagnosed_at
        # Legacy dual-write: pregnancy fields still live on the diabetic table.
        if reproductive is not None:
            entity.is_pregnant = reproductive.is_pregnant
            entity.pregnancy_weeks = reproductive.pregnancy_weeks
        patient.diabetic_history = entity

    @staticmethod
    def _apply_reproductive_health(patient, section, patient_id: str) -> None:
        if section is None:
            return
        entity = patient.reproductive_health or PatientReproductiveHealthModel(
            patient_id=patient_id
        )
        entity.is_pregnant = section.is_pregnant
        entity.pregnancy_weeks = section.pregnancy_weeks
        entity.menopause_status = section.menopause_status
        entity.period_regularity = section.period_regularity
        entity.uses_contraception = section.uses_contraception
        patient.reproductive_health = entity

    async def _apply_eating_habit(
        self,
        patient,
        section,
        patient_id: str,
        *,
        postgres_session: AsyncSession,
    ) -> None:
        # Capture existing relations BEFORE any mutation so we don't lazy-load
        # after a flush in async context (greenlet_spawn error).
        existing_habit = patient.eating_habit
        existing_meal_timings = (
            list(existing_habit.meal_timings) if existing_habit else []
        )
        existing_pref = existing_habit.diet_preferences if existing_habit else None

        # New habits get an explicit eating_habit_id so we never need to flush
        # mid-method to populate the FK target for meal_timings / diet_preferences.
        habit = existing_habit or PatientEatingHabitModel(
            patient_id=patient_id,
            eating_habit_id=uuid.uuid4(),
        )
        habit.meals_per_day = section.meals_per_day
        habit.snacks_count = section.snacks_count
        habit.cuisine_preferences = list(section.cuisine_preferences) or None
        habit.dietary_preferences = list(section.diet_preferences) or None
        habit.diet_preferences_detail = section.diet_preferences_detail
        patient.eating_habit = habit

        habit.meal_timings = await self._upsert_multiple_entities(
            existing_meal_timings,
            [
                # PatientMealTiming.time is a String column — format HH:MM
                PatientMealTimingCreate(
                    meal_type=mt.meal_type,
                    time=mt.time.strftime("%H:%M"),
                )
                for mt in section.meal_timings
            ],
            PatientMealTimingModel,
            "eating_habit_id",
            habit.eating_habit_id,
            postgres_session=postgres_session,
        )

        # Legacy dual-write: PatientDietPreference table holds one row.
        # Store the first item from the list + the detail string.
        if section.diet_preferences:
            pref = existing_pref or PatientDietPreferenceModel(
                eating_habit_id=habit.eating_habit_id,
            )
            pref.preference = section.diet_preferences[0]
            pref.detail = section.diet_preferences_detail
            habit.diet_preferences = pref

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

            # Auto-assign health facility if not already assigned
            if patient.health_facility_id is None:
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

            fetched_ids = {str(cp.care_provider_id) for cp in fetched_care_providers}
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
                raise_http_exception(400, "All care providers already assigned.")

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
            care_provider = await self.care_provider_service.fetch_care_provider(
                care_provider_id
            )
            care_provider = await postgres_session.merge(care_provider)

            if str(care_provider.health_facility_id) != health_facility_id:
                raise_http_exception(400, "Care provider is in a different facility")

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
                raise_http_exception(400, "Patient has no assigned care providers")

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
            care_provider = await self.care_provider_service.fetch_care_provider(
                care_provider_id
            )
            care_provider = await postgres_session.merge(care_provider)

            if str(care_provider.health_facility_id) != health_facility_id:
                raise_http_exception(400, "Care provider is in a different facility")

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
            care_provider = (await postgres_session.execute(stmt)).scalars().first()

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
            stmt = select(exists().where(PatientModel.patient_id == patient_id))
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

    def _mark_profile_section_complete(self, profile_completion, section: str) -> bool:
        if not profile_completion[section]["is_complete"]:
            profile_completion[section]["is_complete"] = True
            return True
        return False
