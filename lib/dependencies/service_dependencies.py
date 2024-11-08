from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.database import get_postgres_session
from lib.models.patient import Patient
from lib.services.ai_conversation_service import AiConversationService
from lib.services.care_provider_profile_service import \
    CareProviderProfileService
from lib.services.chat_service import ChatService
from lib.services.fitness_upload_service import FitnessUploadService
from lib.services.meal_analysis_service import MealAnalysisService
from lib.services.meal_service import MealService
from lib.services.patient_care_provider_service import \
    PatientCareProviderService
from lib.services.patient_connected_app_service import \
    PatientConnectedAppService
from lib.services.patient_plan_service import PatientPlanService
from lib.services.patient_profile_service import PatientProfileService
from lib.services.patient_smbg_service import PatientSmbgService
from lib.services.user_device_service import UserDeviceService
from lib.utils.fitness.processor import FitnessStatsProcessor
from lib.utils.glucose.processor import GlucoseStatsProcessor
from lib.utils.meals.processor import MealStatsProcessor


async def get_user_device_service(
    session: AsyncSession = Depends(get_postgres_session),
) -> UserDeviceService:
    return UserDeviceService(postgres_session=session)


async def get_chat_service(
    session: AsyncSession = Depends(get_postgres_session),
) -> ChatService:
    return ChatService()


async def get_ai_conversation_service() -> AiConversationService:
    return AiConversationService()


async def get_care_provider_profile_service(
    session: AsyncSession = Depends(get_postgres_session),
    chat_service: ChatService = Depends(get_chat_service),
) -> CareProviderProfileService:
    return CareProviderProfileService(
        postgres_session=session, chat_service=chat_service
    )


async def get_patient_profile_service(
    session: AsyncSession = Depends(get_postgres_session),
    chat_service: ChatService = Depends(get_chat_service),
) -> PatientProfileService:
    return PatientProfileService(
        postgres_session=session, chat_service=chat_service
    )


async def get_patient_care_provider_service(
    session: AsyncSession = Depends(get_postgres_session),
    chat_service: ChatService = Depends(get_chat_service),
    care_provider_profile_service: CareProviderProfileService = Depends(
        get_care_provider_profile_service
    ),
    patient_profile_service: PatientProfileService = Depends(
        get_patient_profile_service
    ),
) -> PatientCareProviderService:
    return PatientCareProviderService(
        postgres_session=session,
        chat_service=chat_service,
        care_provider_profile_service=care_provider_profile_service,
        patient_profile_service=patient_profile_service,
    )


async def get_patient_connected_app_service(
    session: AsyncSession = Depends(get_postgres_session),
) -> PatientConnectedAppService:
    return PatientConnectedAppService(postgres_session=session)


async def get_patient_smbg_service(
    session: AsyncSession = Depends(get_postgres_session),
    patient_profile_service: PatientProfileService = Depends(
        get_patient_profile_service
    ),
) -> PatientSmbgService:
    return PatientSmbgService(
        patient_profile_service=patient_profile_service,
        postgres_session=session,
    )


async def get_meal_analysis_service(
    session: AsyncSession = Depends(get_postgres_session),
) -> MealAnalysisService:
    return MealAnalysisService(postgres_session=session)


async def get_meal_service(
    session: AsyncSession = Depends(get_postgres_session),
    meal_analysis_service: MealAnalysisService = Depends(
        get_meal_analysis_service
    ),
    patient_profile_service: PatientProfileService = Depends(
        get_patient_profile_service
    ),
) -> MealService:
    return MealService(
        postgres_session=session,
        meal_analysis_service=meal_analysis_service,
        patient_profile_service=patient_profile_service,
    )


async def get_patient_plan_service(
    session: AsyncSession = Depends(get_postgres_session),
) -> PatientPlanService:
    return PatientPlanService(postgres_session=session)


async def get_glucose_stats_processor(
    request: Request,
    session: AsyncSession = Depends(get_postgres_session),
    current_patient: Patient = Depends(get_current_patient),
    meal_service: MealService = Depends(get_meal_service),
    patient_connected_app_service: PatientConnectedAppService = Depends(
        get_patient_connected_app_service
    ),
) -> GlucoseStatsProcessor:
    clickhouse_store = request.state.context.clickhouse_store
    patient_id = str(current_patient.patient_id)
    return GlucoseStatsProcessor(
        clickhouse_store,
        session,
        meal_service,
        patient_connected_app_service,
        patient_id,
    )


async def get_meal_stats_processor(
    request: Request,
    session: AsyncSession = Depends(get_postgres_session),
    current_patient: Patient = Depends(get_current_patient),
    glucose_stats_processor: GlucoseStatsProcessor = Depends(
        get_glucose_stats_processor
    ),
    patient_profile_service: PatientProfileService = Depends(
        get_patient_profile_service
    ),
    patient_plan_service: PatientPlanService = Depends(
        get_patient_plan_service
    ),
) -> MealStatsProcessor:
    clickhouse_store = request.state.context.clickhouse_store
    patient_id = str(current_patient.patient_id)
    return MealStatsProcessor(
        session,
        clickhouse_store,
        glucose_stats_processor,
        patient_profile_service,
        patient_plan_service,
        patient_id,
    )


async def get_fitness_stats_processor(
    request: Request,
    current_patient: Patient = Depends(get_current_patient),
) -> FitnessStatsProcessor:
    clickhouse_store = request.state.context.clickhouse_store
    patient_id = str(current_patient.patient_id)
    return FitnessStatsProcessor(clickhouse_store, patient_id)


async def get_fitness_upload_service(
    request: Request,
    session: AsyncSession = Depends(get_postgres_session),
    current_patient: Patient = Depends(get_current_patient),
) -> FitnessUploadService:
    clickhouse_store = request.state.context.clickhouse_store
    fitness_sync_store = request.app.state.fitness_sync_store

    return FitnessUploadService(
        clickhouse_store,
        fitness_sync_store,
        session,
        str(current_patient.patient_id),
    )
