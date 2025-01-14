from typing import cast

from punq import Container, Scope
from sqlalchemy.ext.asyncio import AsyncSession

from lib.core.clickhouse_store import ClickHouseStore
# Services
from lib.core.postgres_store import PostgresStore
from lib.services.ai_conversation_service import AiConversationService
from lib.services.care_provider_profile_service import \
    CareProviderProfileService
from lib.services.cgm_service import CGMService
from lib.services.chat.chat_management_service import ChatManagementService
from lib.services.chat.chat_messaging_service import ChatMessagingService
from lib.services.chat.chat_notification_service import ChatNotificationService
from lib.services.chat.chat_participant_service import ChatParticipantService
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
# Processors
from lib.services.user_device_service import UserDeviceService
from lib.utils.fitness.processor import FitnessStatsProcessor
from lib.utils.glucose.processor import GlucoseStatsProcessor
from lib.utils.meals.processor import MealStatsProcessor

# Initialize Container
container = Container()

# 🔹 Core Dependencies
container.register(PostgresStore, PostgresStore)
container.register(ClickHouseStore, ClickHouseStore)
container.register(
    AsyncSession,
    factory=lambda: cast(
        PostgresStore, container.resolve(PostgresStore)
    ).session_local(),
    scope=Scope.singleton,
)

# 🔹 Basic Services
container.register(ChatMessagingService, ChatMessagingService)
container.register(ChatNotificationService, ChatNotificationService)
container.register(ChatParticipantService, ChatParticipantService)
container.register(ChatManagementService, ChatManagementService)
container.register(AiConversationService, AiConversationService)
container.register(MealReportService, MealReportService)

# 🔹 Patient Profile Service
container.register(
    PatientProfileService,
    lambda: PatientProfileService(
        postgres_session=cast(AsyncSession, container.resolve(AsyncSession)),
        chat_notification_service=cast(
            ChatNotificationService, container.resolve(ChatNotificationService)
        ),
        chat_management_service=cast(
            ChatManagementService, container.resolve(ChatManagementService)
        ),
    ),
)

# 🔹 Care Provider Profile Service
container.register(
    CareProviderProfileService,
    lambda: CareProviderProfileService(
        postgres_session=cast(AsyncSession, container.resolve(AsyncSession)),
        patient_service=cast(
            PatientProfileService, container.resolve(PatientProfileService)
        ),
        chat_management_service=cast(
            ChatManagementService, container.resolve(ChatManagementService)
        ),
        chat_notification_service=cast(
            ChatNotificationService, container.resolve(ChatNotificationService)
        ),
    ),
)

# 🔹 Health Facility Service
container.register(
    HealthFacilityService,
    lambda: HealthFacilityService(
        postgres_session=cast(AsyncSession, container.resolve(AsyncSession)),
    ),
)

# 🔹 Patient Connected App Service
container.register(
    PatientConnectedAppService,
    lambda: PatientConnectedAppService(
        postgres_session=cast(AsyncSession, container.resolve(AsyncSession)),
    ),
)

# 🔹 Patient SMBG Service
container.register(
    PatientSmbgService,
    lambda: PatientSmbgService(
        postgres_session=cast(AsyncSession, container.resolve(AsyncSession)),
        patient_profile_service=cast(
            PatientProfileService, container.resolve(PatientProfileService)
        ),
    ),
)

# 🔹 Patient Vital Service
container.register(
    PatientVitalService,
    lambda: PatientVitalService(
        postgres_session=cast(AsyncSession, container.resolve(AsyncSession)),
        patient_profile_service=cast(
            PatientProfileService, container.resolve(PatientProfileService)
        ),
    ),
)

# 🔹 Patient Plan Service
container.register(
    PatientPlanService,
    lambda: PatientPlanService(
        postgres_session=cast(AsyncSession, container.resolve(AsyncSession)),
    ),
)

# 🔹 Meal Analysis Service
container.register(
    MealAnalysisService,
    lambda: MealAnalysisService(
        postgres_session=cast(AsyncSession, container.resolve(AsyncSession)),
    ),
)

# 🔹 Meal Service (Nested with Meal Analysis and Patient Profile)
container.register(
    MealService,
    lambda: MealService(
        postgres_session=cast(AsyncSession, container.resolve(AsyncSession)),
        meal_analysis_service=cast(
            MealAnalysisService, container.resolve(MealAnalysisService)
        ),
        patient_profile_service=cast(
            PatientProfileService, container.resolve(PatientProfileService)
        ),
    ),
)

# 🔹 Fitness Stats Processor
container.register(
    FitnessStatsProcessor,
    lambda: FitnessStatsProcessor(
        clickhouse_store=container.resolve(ClickHouseStore)
    ),
)

# 🔹 Glucose Stats Processor
container.register(
    GlucoseStatsProcessor,
    lambda: GlucoseStatsProcessor(
        clickhouse_store=container.resolve(ClickHouseStore),
        meal_service=container.resolve(MealService),
        fitness_stats_processor=cast(
            FitnessStatsProcessor, container.resolve(FitnessStatsProcessor)
        ),
    ),
)

# 🔹 Meal Stats Processor
container.register(
    MealStatsProcessor,
    lambda: MealStatsProcessor(
        postgres_session=cast(AsyncSession, container.resolve(AsyncSession)),
        clickhouse_store=container.resolve(ClickHouseStore),
        glucose_stats_processor=container.resolve(GlucoseStatsProcessor),
        patient_profile_service=container.resolve(PatientProfileService),
        patient_plan_service=container.resolve(PatientPlanService),
    ),
)

# 🔹 Fitness Report Service
container.register(FitnessReportService, FitnessReportService)

# 🔹 Fitness Upload Service
container.register(
    FitnessUploadService,
    lambda: FitnessUploadService(
        postgres_session=cast(AsyncSession, container.resolve(AsyncSession)),
        clickhouse_store=container.resolve(ClickHouseStore),
        fitness_sync_store=None,  # Provide this if necessary
    ),
)

# 🔹 User Device Service
container.register(
    UserDeviceService,
    lambda: UserDeviceService(
        postgres_session=cast(AsyncSession, container.resolve(AsyncSession)),
    ),
)

# 🔹 Package Service
container.register(
    PackageService,
    lambda: PackageService(
        postgres_session=cast(AsyncSession, container.resolve(AsyncSession)),
        patient_service=cast(
            PatientProfileService, container.resolve(PatientProfileService)
        ),
        care_provider_service=cast(
            CareProviderProfileService,
            container.resolve(CareProviderProfileService),
        ),
        chat_management_service=cast(
            ChatManagementService, container.resolve(ChatManagementService)
        ),
        chat_notification_service=cast(
            ChatNotificationService, container.resolve(ChatNotificationService)
        ),
    ),
)

# 🔹 CGM Service
container.register(
    CGMService,
    lambda: CGMService(
        clickhouse_store=container.resolve(ClickHouseStore),
        postgres_session=cast(AsyncSession, container.resolve(AsyncSession)),
    ),
)
