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
from lib.core.qdrant_store import QdrantStore
from lib.managers.celery_task_manager import CeleryTaskManager
from lib.services.ai_conversation_service.ai_conversation_service import (
    AiConversationService,
)
from lib.services.ai_conversation_service.ai_conversation_service_v2 import (
    AiConversationServiceV2,
)
from lib.services.ai_conversation_service_v1.ai_conversation_service_v1 import (
    AIConversationServiceV1,
)
from lib.services.ai_conversation_service_v1.context_builder import (
    AIConversationContextBuilder,
)
from lib.services.ai_conversation_service_v1.context_resolver import (
    AIConversationContextResolver,
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
from lib.services.dashboard_metrics.cgm_metrics_service import (
    CGMMetricsService,
)
from lib.services.dashboard_metrics.fitneess_metrics_service import (
    FitnessMetricsService,
)
from lib.services.dashboard_metrics.meal_metrics_service import (
    MealMetricsService,
)
from lib.services.dashboard_metrics.patient_metrics_service import (
    PatientMetricsService,
)
from lib.services.dashboard_metrics.smbg_metrics_service import (
    SMBGMetricsService,
)
from lib.services.file_content_extractor import FileContentExtractorService
from lib.services.fitness_report_service import FitnessReportService
from lib.services.fitness_upload_service import FitnessUploadService
from lib.services.health_facility_service import HealthFacilityService
from lib.services.libreview_service import LibreViewService
from lib.services.meal_analysis_service import MealAnalysisService
from lib.services.meal_report_service import MealReportService
from lib.services.meal_service import MealService
from lib.services.meal_vector_service.meal_vector_service import (
    MealVectorService,
)
from lib.services.package_service import PackageService
from lib.services.patient_connected_app_service import (
    PatientConnectedAppService,
)
from lib.services.patient_document_service import PatientDocumentService
from lib.services.patient_package_assignment_service import (
    PatientPackageAssignmentService,
)
from lib.services.patient_plan_service import PatientPlanService
from lib.services.patient_profile_service import PatientProfileService
from lib.services.patient_profile_vector_service.patient_profile_vector_service import (
    PatientProfileVectorService,
)
from lib.services.patient_report_service import PatientReportService
from lib.services.patient_sleep_service import PatientSleepService
from lib.services.patient_smbg_service import PatientSmbgService
from lib.services.patient_vital_service import PatientVitalService

# Processors
from lib.services.prescription_analysis_service import (
    PrescriptionAnalysisService,
)
from lib.services.prescription_service import PrescriptionService
from lib.services.qdrant_search_engine.intent_cache import IntentCache
from lib.services.qdrant_search_engine.qdrant_search_engine import (
    QdrantSearchEngine,
)
from lib.services.sleep_report_service import SleepReportService
from lib.services.smbg_vector_service.smbg_vector_service import (
    SMBGVectorService,
)
from lib.services.sqs_service import SQSService
from lib.services.token_usage_service import TokenUsageService
from lib.services.user_device_service import UserDeviceService
from lib.utils.fitness.processor import FitnessStatsProcessor
from lib.utils.cgm.processor import CGMStatsProcessor
from lib.utils.meals.processor import MealStatsProcessor
from lib.utils.sleep.sleep_stats_processor import SleepStatsProcessor
from lib.utils.smbg.processor import SMBGStatsProcessor
from lib.services.cgm_vector_service import CGMVectorService

# Initialize Container
container = Container()

# 🔹 Core Dependencies
container.register(PostgresStore, PostgresStore, scope=Scope.singleton)
container.register(ClickHouseStore, ClickHouseStore, scope=Scope.singleton)
container.register(QdrantStore, QdrantStore, scope=Scope.singleton)
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
    "patient_documents",
    factory=lambda: cast(
        MongoStore, container.resolve(MongoStore)
    ).get_collection("patient_documents"),
    scope=Scope.singleton,
)


container.register(
    CeleryTaskManager,
    lambda: CeleryTaskManager(app=celery),
    scope=Scope.singleton,
)


# CacheStore
for namespace in [
    "fitness_sync",
    "user_otp",
    "user_session",
    "libreview_sync",
    "ai_conversation_intent_context",
    "patient_profile",
    "cgm_qdrant_sync",
    "cgm_sync",
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
        profile_vector_service=cast(
            PatientProfileVectorService,
            container.resolve(PatientProfileVectorService),
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
        smbg_vector_service=cast(
            SMBGVectorService, container.resolve(SMBGVectorService)
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

# 🔹 Patient Report Service
container.register(
    PatientReportService,
    lambda: PatientReportService(
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
        patient_profile_service=cast(
            PatientProfileService, container.resolve(PatientProfileService)
        ),
        file_content_extractor_service=cast(
            FileContentExtractorService,
            container.resolve(FileContentExtractorService),
        ),
    ),
)

# 🔹 Patient Document Service
container.register(
    PatientDocumentService,
    lambda: PatientDocumentService(
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
        qdrant_store=cast(QdrantStore, container.resolve(QdrantStore)),
        patient_profile_service=cast(
            PatientProfileService, container.resolve(PatientProfileService)
        ),
        file_content_extractor_service=cast(
            FileContentExtractorService,
            container.resolve(FileContentExtractorService),
        ),
        patient_document_collection=cast(
            MongoStore, container.resolve("patient_documents")
        ),
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
        meal_vector_service=cast(
            MealVectorService, container.resolve(MealVectorService)
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
        meal_report_service=container.resolve(MealReportService),
    ),
)

# 🔹 SMBG Stats Processor
container.register(
    SMBGStatsProcessor,
    lambda: SMBGStatsProcessor(
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
        patient_profile_service=container.resolve(PatientProfileService),
        patient_plan_service=container.resolve(PatientPlanService),
        meal_stats_processor=container.resolve(MealStatsProcessor),
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

# 🔹 Ai Conversation Service V2
container.register(
    AiConversationServiceV2,
    lambda: AiConversationServiceV2(
        qdrant_search_engine=cast(
            QdrantSearchEngine, container.resolve(QdrantSearchEngine)
        )
    ),
)


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

# 🔹 CGM Vector Service
container.register(
    CGMVectorService,
    lambda: CGMVectorService(
        qdrant_store=cast(QdrantStore, container.resolve(QdrantStore))
    ),
)

# 🔹 Meal Vector Service
container.register(
    MealVectorService,
    lambda: MealVectorService(
        qdrant_store=cast(QdrantStore, container.resolve(QdrantStore))
    ),
)

# 🔹 SMBG Vector Service
container.register(
    SMBGVectorService,
    lambda: SMBGVectorService(
        qdrant_store=cast(QdrantStore, container.resolve(QdrantStore))
    ),
)

# 🔹 Patient Profile Vector Service
container.register(
    PatientProfileVectorService,
    lambda: PatientProfileVectorService(
        qdrant_store=cast(QdrantStore, container.resolve(QdrantStore))
    ),
)


# 🔹 Intent Cache
container.register(
    IntentCache,
    lambda: IntentCache(
        intent_cache_store=cast(
            CacheStore, container.resolve("ai_conversation_intent_context")
        )
    ),
)

# 🔹 Qdrant Search Engine
container.register(
    QdrantSearchEngine,
    lambda: QdrantSearchEngine(
        qdrant_store=cast(QdrantStore, container.resolve(QdrantStore)),
        intent_cache=cast(IntentCache, container.resolve(IntentCache)),
    ),
)

# 🔹 AI Conversation V1
container.register(
    AIConversationServiceV1,
    lambda: AIConversationServiceV1(
        context_builder=cast(
            AIConversationContextBuilder,
            container.resolve(AIConversationContextBuilder),
        )
    ),
)

# 🔹 AI Conversation Context Builder
container.register(
    AIConversationContextBuilder,
    lambda: AIConversationContextBuilder(
        patient_profile_service=cast(
            PatientProfileService, container.resolve(PatientProfileService)
        ),
        ai_messages_collection=cast(
            MongoStore,
            container.resolve("ai_conversation_messages_collection"),
        ),
        qdrant_search_engine=cast(
            QdrantSearchEngine, container.resolve(QdrantSearchEngine)
        ),
        context_resolver=cast(
            AIConversationContextResolver,
            container.resolve(AIConversationContextResolver),
        ),
    ),
)

# 🔹 AI Conversation Context Resolver
container.register(
    AIConversationContextResolver,
    lambda: AIConversationContextResolver(
        patient_profile_service=cast(
            PatientProfileService, container.resolve(PatientProfileService)
        ),
        patient_profile_store=cast(
            CacheStore, container.resolve("patient_profile")
        ),
    ),
)


# 🔹 Patient Metrics Service
container.register(
    PatientMetricsService,
    lambda: PatientMetricsService(),
)

# 🔹 Meal Metrics Service
container.register(
    MealMetricsService,
    lambda: MealMetricsService(),
)

# 🔹 SMBG Metrics Service
container.register(
    SMBGMetricsService,
    lambda: SMBGMetricsService(),
)

# 🔹 CGM Metrics Service
container.register(
    CGMMetricsService,
    lambda: CGMMetricsService(
        cgm_report_collection=container.resolve("cgm_report_collection"),
    ),
)

# 🔹 Fitness Metrics Service
container.register(
    FitnessMetricsService,
    lambda: FitnessMetricsService(
        fitness_report_collection=container.resolve(
            "fitness_report_collection"
        )
    ),
)


# 🔹 File Content Extractor Service
container.register(FileContentExtractorService, FileContentExtractorService)
