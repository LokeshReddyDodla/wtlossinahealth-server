from typing import cast

from punq import Container, Scope
from sqlalchemy.ext.asyncio import AsyncSession

from lib.core.cache_store import CacheStore
from lib.core.celery_app import celery
from lib.core.clickhouse_store import ClickHouseStore
from decouple import config

# Services
from lib.core.mongo_store import MongoStore
from lib.core.postgres_store import PostgresStore
from lib.managers.celery_task_manager import CeleryTaskManager
from lib.services.ai_conversation_service.ai_conversation_service import (
    AiConversationService,
)
from lib.services.care_provider_profile_service import (
    CareProviderProfileService,
)
from lib.services.cgm_report_service import CGMReportService
from lib.services.cgm_upload_service import CGMUploadService
from lib.services.chat.chat_management_service import ChatManagementService
from lib.services.chat.chat_messaging_service import ChatMessagingService
from lib.services.chat.chat_notification_service import ChatNotificationService
from lib.services.chat.chat_participant_service import ChatParticipantService
from lib.services.fitness_report_service import FitnessReportService
from lib.services.fitness_upload_service import FitnessUploadService
from lib.services.health_facility_service import HealthFacilityService
from lib.services.libreview_service import LibreViewService
from lib.services.meal_analysis_service import MealAnalysisService
from lib.services.meal_report_service import MealReportService
from lib.services.meal_service import MealService
from lib.services.package_service import PackageService
from lib.services.patient_connected_app_service import (
    PatientConnectedAppService,
)
from lib.services.patient_package_assignment_service import (
    PatientPackageAssignmentService,
)
from lib.services.patient_plan_service import PatientPlanService
from lib.services.patient_profile_service import PatientProfileService
from lib.services.patient_sleep_service import PatientSleepService
from lib.services.patient_smbg_service import PatientSmbgService
from lib.services.patient_vital_service import PatientVitalService

# Processors
from lib.services.prescription_analysis_service import (
    PrescriptionAnalysisService,
)
from lib.services.prescription_service import PrescriptionService
from lib.services.sleep_report_service import SleepReportService
from lib.services.sqs_service import SQSService
from lib.services.token_usage_service import TokenUsageService
from lib.services.user_device_service import UserDeviceService
from lib.utils.fitness.processor import FitnessStatsProcessor
from lib.utils.cgm.processor import CGMStatsProcessor
from lib.utils.meals.processor import MealStatsProcessor
from lib.utils.sleep.sleep_stats_processor import SleepStatsProcessor

# Initialize Container
container = Container()

# 🔹 Core Dependencies
container.register(PostgresStore, PostgresStore, scope=Scope.singleton)
container.register(ClickHouseStore, ClickHouseStore, scope=Scope.singleton)
container.register(
    AsyncSession,
    factory=lambda: cast(
        PostgresStore, container.resolve(PostgresStore)
    ).session_local(),
    scope=Scope.transient,
)
container.register(MongoStore, MongoStore, scope=Scope.singleton)
container.register(
    "cgm_report_collection",
    factory=lambda: cast(
        MongoStore, container.resolve(MongoStore)
    ).get_collection("cgm_reports"),
    scope=Scope.singleton,
)
container.register(
    "fitness_report_collection",
    factory=lambda: cast(
        MongoStore, container.resolve(MongoStore)
    ).get_collection("fitness_reports"),
    scope=Scope.singleton,
)
container.register(
    "sleep_report_collection",
    factory=lambda: cast(
        MongoStore, container.resolve(MongoStore)
    ).get_collection("sleep_reports"),
    scope=Scope.singleton,
)
container.register(
    "meal_report_collection",
    factory=lambda: cast(
        MongoStore, container.resolve(MongoStore)
    ).get_collection("meal_reports"),
    scope=Scope.singleton,
)
container.register(
    "ai_conversation_messages_collection",
    factory=lambda: cast(
        MongoStore, container.resolve(MongoStore)
    ).get_collection("ai_conversation_messages"),
    scope=Scope.singleton,
)
container.register(
    "chat_messages_collection",
    factory=lambda: cast(
        MongoStore, container.resolve(MongoStore)
    ).get_collection("chat_messages"),
    scope=Scope.singleton,
)
container.register(
    "chats_collection",
    factory=lambda: cast(
        MongoStore, container.resolve(MongoStore)
    ).get_collection("chats"),
    scope=Scope.singleton,
)


container.register(
    CeleryTaskManager,
    lambda: CeleryTaskManager(app=celery),
    scope=Scope.singleton,
)


# CacheStores
for namespace in [
    "fitness_sync",
    "user_otp",
    "user_sessions",
    "libreview_sync",
]:
    container.register(
        namespace,
        lambda ns=namespace: CacheStore(namespace=ns),
    )

# 🔹 Libreview SQS Service
container.register(
    "libreview_sync_queue",
    lambda: SQSService(
        queue_url=str(
            config("LIBREVIEW_SYNC_QUEUE_URL"),
        ),
        message_group_id="libreview",
    ),
    scope=Scope.singleton,  # or transient if you want a fresh instance each time
)

# 🔹 Chat Services
container.register(ChatMessagingService, ChatMessagingService)
container.register(ChatNotificationService, ChatNotificationService)
container.register(ChatParticipantService, ChatParticipantService)
container.register(ChatManagementService, ChatManagementService)


# 🔹 Patient Profile Service
container.register(
    PatientProfileService,
    lambda: PatientProfileService(
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
        care_provider_service=cast(
            CareProviderProfileService,
            container.resolve(CareProviderProfileService),
        ),
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
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
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
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
    ),
)

# 🔹 Patient Connected App Service
container.register(
    PatientConnectedAppService,
    lambda: PatientConnectedAppService(
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
    ),
)

# 🔹 Patient SMBG Service
container.register(
    PatientSmbgService,
    lambda: PatientSmbgService(
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
        patient_profile_service=cast(
            PatientProfileService, container.resolve(PatientProfileService)
        ),
    ),
)

# 🔹 Patient Vital Service
container.register(
    PatientVitalService,
    lambda: PatientVitalService(
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
        patient_profile_service=cast(
            PatientProfileService, container.resolve(PatientProfileService)
        ),
    ),
)

# 🔹 Patient Sleep Service
container.register(
    PatientSleepService,
    lambda: PatientSleepService(
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
        patient_profile_service=cast(
            PatientProfileService, container.resolve(PatientProfileService)
        ),
    ),
)

# 🔹 Patient Plan Service
container.register(
    PatientPlanService,
    lambda: PatientPlanService(
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
    ),
)

# 🔹 Meal Analysis Service
container.register(
    MealAnalysisService,
    lambda: MealAnalysisService(
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
        token_usage_service=cast(
            TokenUsageService, container.resolve(TokenUsageService)
        ),
        selected_ai_model="gpt-4o",
        ai_model_provider="openai",
    ),
)

# 🔹 Meal Service (Nested with Meal Analysis and Patient Profile)
container.register(
    MealService,
    lambda: MealService(
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
        meal_analysis_service=cast(
            MealAnalysisService, container.resolve(MealAnalysisService)
        ),
        patient_profile_service=cast(
            PatientProfileService, container.resolve(PatientProfileService)
        ),
    ),
)

# 🔹 Prescription Service
container.register(
    PrescriptionService,
    lambda: PrescriptionService(
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
        prescription_analysis_service=cast(
            PrescriptionAnalysisService,
            container.resolve(PrescriptionAnalysisService),
        ),
        patient_profile_service=cast(
            PatientProfileService, container.resolve(PatientProfileService)
        ),
    ),
)


# 🔹 Prescription Analysis Service
container.register(
    PrescriptionAnalysisService,
    lambda: PrescriptionAnalysisService(
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
        token_usage_service=cast(
            TokenUsageService, container.resolve(TokenUsageService)
        ),
        selected_ai_model="gpt-4o",
        ai_model_provider="openai",
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
    CGMStatsProcessor,
    lambda: CGMStatsProcessor(
        clickhouse_store=container.resolve(ClickHouseStore),
        meal_service=container.resolve(MealService),
        fitness_stats_processor=cast(
            FitnessStatsProcessor, container.resolve(FitnessStatsProcessor)
        ),
        meal_report_service=cast(
            MealReportService, container.resolve(MealReportService)
        ),
    ),
)

# 🔹 Meal Stats Processor
container.register(
    MealStatsProcessor,
    lambda: MealStatsProcessor(
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
        clickhouse_store=container.resolve(ClickHouseStore),
        cgm_stats_processor=container.resolve(CGMStatsProcessor),
        patient_profile_service=container.resolve(PatientProfileService),
        patient_plan_service=container.resolve(PatientPlanService),
    ),
)

# 🔹 Sleep Stats Processor
container.register(
    SleepStatsProcessor,
    lambda: SleepStatsProcessor(
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
    ),
)

# 🔹 Sleep Report Service
container.register(
    SleepReportService,
    lambda: SleepReportService(
        sleep_report_collection=container.resolve("sleep_report_collection")
    ),
)

# 🔹 Fitness Report Service
container.register(
    FitnessReportService,
    lambda: FitnessReportService(
        fitness_report_collection=container.resolve(
            "fitness_report_collection"
        )
    ),
)

# 🔹 Meal Report Service
container.register(
    MealReportService,
    lambda: MealReportService(
        meal_report_collection=container.resolve("meal_report_collection")
    ),
)

# 🔹 CGM Report Service
container.register(
    CGMReportService,
    lambda: CGMReportService(
        cgm_report_collection=container.resolve("cgm_report_collection"),
        meal_report_service=cast(
            MealReportService, container.resolve(MealReportService)
        ),
        fitness_report_service=cast(
            FitnessReportService, container.resolve(FitnessReportService)
        ),
    ),
)

# 🔹 Fitness Upload Service
container.register(
    FitnessUploadService,
    lambda: FitnessUploadService(
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
        clickhouse_store=container.resolve(ClickHouseStore),
        fitness_sync_store=container.resolve("fitness_sync"),
    ),
)

# 🔹 User Device Service
container.register(
    UserDeviceService,
    lambda: UserDeviceService(
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
    ),
)

# 🔹 Patient Package Assignment Service
container.register(
    PatientPackageAssignmentService,
    lambda: PatientPackageAssignmentService(
        patient_service=cast(
            PatientProfileService, container.resolve(PatientProfileService)
        ),
        package_service=container.resolve(PackageService),
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
    ),
)


# 🔹 Package Service
container.register(
    PackageService,
    lambda: PackageService(
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
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


# 🔹 CGM Upload Service
container.register(
    CGMUploadService,
    lambda: CGMUploadService(
        clickhouse_store=container.resolve(ClickHouseStore),
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
    ),
)

# 🔹 Ai Conversation Service
container.register(AiConversationService, AiConversationService)


# 🔹 Ai Patient Token Usage Service
container.register(
    TokenUsageService,
    lambda: TokenUsageService(
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
    ),
)

# 🔹 LibreView Service
container.register(
    LibreViewService,
    lambda: LibreViewService(
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
        patient_connected_app_service=cast(
            PatientConnectedAppService,
            container.resolve(PatientConnectedAppService),
        ),
        libreview_sync_queue=cast(
            SQSService, container.resolve("libreview_sync_queue")
        ),
        libreview_sync_store=cast(
            CacheStore, container.resolve("libreview_sync")
        ),
    ),
)
