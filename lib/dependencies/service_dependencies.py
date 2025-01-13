from fastapi import Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from lib.dependencies.database import get_postgres_session
from lib.models.patient import Patient
from lib.services.ai_conversation_service import AiConversationService
from lib.services.care_provider_profile_service import \
    CareProviderProfileService
from lib.services.cgm_service import CGMService
from lib.services.chat.chat_management_service import ChatManagementService
from lib.services.chat.chat_messaging_service import ChatMessagingService
from lib.services.chat.chat_notification_service import ChatNotificationService
from lib.services.fitness_report_service import FitnessReportService
from lib.services.fitness_upload_service import FitnessUploadService
from lib.services.health_facility_service import HealthFacilityService
from lib.services.meal_analysis_service import MealAnalysisService
from lib.services.meal_service import MealService
from lib.services.package_service import PackageService
from lib.services.patient_connected_app_service import \
    PatientConnectedAppService
from lib.services.patient_plan_service import PatientPlanService
from lib.services.patient_profile_service import PatientProfileService
from lib.services.patient_smbg_service import PatientSmbgService
from lib.services.patient_vital_service import PatientVitalService
from lib.services.user_device_service import UserDeviceService
from lib.utils.fitness.processor import FitnessStatsProcessor
from lib.utils.glucose.processor import GlucoseStatsProcessor
from lib.utils.meals.processor import MealStatsProcessor


async def get_user_device_service(
    session: AsyncSession = Depends(get_postgres_session),
) -> UserDeviceService:
    return UserDeviceService(postgres_session=session)


async def get_chat_messaging_service() -> ChatMessagingService:
    return ChatMessagingService()


async def get_chat_notification_service() -> ChatNotificationService:
    return ChatNotificationService()


async def get_chat_management_service() -> ChatManagementService:
    return ChatManagementService()


async def get_ai_conversation_service() -> AiConversationService:
    return AiConversationService()


async def get_patient_profile_service(
    session: AsyncSession = Depends(get_postgres_session),
    chat_notification_service=Depends(get_chat_notification_service),
    chat_management_service=Depends(get_chat_management_service),
) -> PatientProfileService:
    return PatientProfileService(
        postgres_session=session,
        chat_notification_service=chat_notification_service,
        chat_management_service=chat_management_service,
    )


async def get_care_provider_profile_service(
    session: AsyncSession = Depends(get_postgres_session),
    patient_service=Depends(get_patient_profile_service),
    chat_management_service=Depends(get_chat_management_service),
    chat_notification_service=Depends(get_chat_notification_service),
) -> CareProviderProfileService:
    return CareProviderProfileService(
        postgres_session=session,
        patient_service=patient_service,
        chat_management_service=chat_management_service,
        chat_notification_service=chat_notification_service,
    )


async def get_health_facility_service(
    session: AsyncSession = Depends(get_postgres_session),
) -> HealthFacilityService:
    return HealthFacilityService(postgres_session=session)


async def get_package_service(
    session: AsyncSession = Depends(get_postgres_session),
    patient_service=Depends(get_patient_profile_service),
    care_provider_service=Depends(get_care_provider_profile_service),
    chat_management_service=Depends(get_chat_management_service),
    chat_notification_service=Depends(get_chat_notification_service),
) -> PackageService:
    return PackageService(
        postgres_session=session,
        patient_service=patient_service,
        care_provider_service=care_provider_service,
        chat_management_service=chat_management_service,
        chat_notification_service=chat_notification_service,
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


async def get_patient_vital_service(
    session: AsyncSession = Depends(get_postgres_session),
    patient_profile_service: PatientProfileService = Depends(
        get_patient_profile_service
    ),
) -> PatientVitalService:
    return PatientVitalService(
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


async def get_cgm_service(
    request: Request,
    session: AsyncSession = Depends(get_postgres_session),
) -> CGMService:
    clickhouse_store = request.state.context.clickhouse_store
    return CGMService(
        clickhouse_store=clickhouse_store, postgres_session=session
    )


async def get_fitness_stats_processor(
    request: Request,
) -> FitnessStatsProcessor:
    clickhouse_store = request.state.context.clickhouse_store
    return FitnessStatsProcessor(clickhouse_store)


async def get_fitness_report_service(request: Request) -> FitnessReportService:
    return FitnessReportService()


async def get_glucose_stats_processor(
    request: Request,
    meal_service: MealService = Depends(get_meal_service),
    fitness_stats_processor: FitnessStatsProcessor = Depends(
        get_fitness_stats_processor
    ),
) -> GlucoseStatsProcessor:
    clickhouse_store = request.state.context.clickhouse_store
    return GlucoseStatsProcessor(
        clickhouse_store=clickhouse_store,
        meal_service=meal_service,
        fitness_stats_processor=fitness_stats_processor,
    )


async def get_meal_stats_processor(
    request: Request,
    session: AsyncSession = Depends(get_postgres_session),
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
    return MealStatsProcessor(
        session,
        clickhouse_store,
        glucose_stats_processor,
        patient_profile_service,
        patient_plan_service,
    )


async def get_fitness_upload_service(
    request: Request,
    session: AsyncSession = Depends(get_postgres_session),
) -> FitnessUploadService:
    clickhouse_store = request.state.context.clickhouse_store
    fitness_sync_store = request.app.state.fitness_sync_store

    return FitnessUploadService(
        clickhouse_store,
        fitness_sync_store,
        session,
    )
