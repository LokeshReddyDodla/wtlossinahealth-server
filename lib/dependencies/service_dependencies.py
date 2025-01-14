from typing import cast

from lib.core.container import container
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
from lib.services.meal_report_service import MealReportService
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


async def get_user_device_service() -> UserDeviceService:
    return cast(UserDeviceService, container.resolve(UserDeviceService))


async def get_chat_messaging_service() -> ChatMessagingService:
    return cast(ChatMessagingService, container.resolve(ChatMessagingService))


async def get_chat_notification_service() -> ChatNotificationService:
    return cast(
        ChatNotificationService, container.resolve(ChatNotificationService)
    )


async def get_chat_management_service() -> ChatManagementService:
    return cast(
        ChatManagementService, container.resolve(ChatManagementService)
    )


async def get_ai_conversation_service() -> AiConversationService:
    return cast(
        AiConversationService, container.resolve(AiConversationService)
    )


async def get_patient_profile_service() -> PatientProfileService:
    return cast(
        PatientProfileService, container.resolve(PatientProfileService)
    )


async def get_care_provider_profile_service() -> CareProviderProfileService:
    return cast(
        CareProviderProfileService,
        container.resolve(CareProviderProfileService),
    )


async def get_health_facility_service() -> HealthFacilityService:
    return cast(
        HealthFacilityService,
        container.resolve(HealthFacilityService),
    )


async def get_package_service() -> PackageService:
    return cast(
        PackageService,
        container.resolve(PackageService),
    )


async def get_patient_connected_app_service() -> PatientConnectedAppService:
    return cast(
        PatientConnectedAppService,
        container.resolve(PatientConnectedAppService),
    )


async def get_patient_smbg_service() -> PatientSmbgService:
    return cast(
        PatientSmbgService,
        container.resolve(PatientSmbgService),
    )


async def get_patient_vital_service() -> PatientVitalService:
    return cast(
        PatientVitalService,
        container.resolve(PatientVitalService),
    )


async def get_meal_analysis_service() -> MealAnalysisService:
    return cast(
        MealAnalysisService,
        container.resolve(MealAnalysisService),
    )


async def get_meal_service() -> MealService:
    return cast(
        MealService,
        container.resolve(MealService),
    )


async def get_patient_plan_service() -> PatientPlanService:
    return cast(
        PatientPlanService,
        container.resolve(PatientPlanService),
    )


async def get_cgm_service() -> CGMService:
    return cast(
        CGMService,
        container.resolve(CGMService),
    )


async def get_fitness_stats_processor() -> FitnessStatsProcessor:
    return cast(
        FitnessStatsProcessor,
        container.resolve(FitnessStatsProcessor),
    )


async def get_fitness_report_service() -> FitnessReportService:
    return cast(FitnessReportService, container.resolve(FitnessReportService))


async def get_glucose_stats_processor() -> GlucoseStatsProcessor:
    return cast(
        GlucoseStatsProcessor, container.resolve(GlucoseStatsProcessor)
    )


async def get_meal_stats_processor() -> MealStatsProcessor:
    return cast(MealStatsProcessor, container.resolve(MealStatsProcessor))


async def get_meal_report_service() -> MealReportService:
    return cast(MealReportService, container.resolve(MealReportService))


async def get_fitness_upload_service() -> FitnessUploadService:
    return cast(FitnessUploadService, container.resolve(FitnessUploadService))
