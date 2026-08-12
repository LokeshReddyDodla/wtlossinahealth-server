from typing import cast

from punq import Container, Scope
from sqlalchemy.ext.asyncio import AsyncSession

from lib.core.cache_store import CacheStore
from lib.core.clickhouse_store import ClickHouseStore
from decouple import config

# Services
from lib.core.mongo_store import MongoStore
from lib.core.postgres_store import PostgresStore
from lib.core.qdrant_store import QdrantStore
from lib.managers.arq_task_manager import ArqTaskManager, get_arq_task_manager
from lib.services.care_intent_service import CareIntentService
from lib.services.care_provider_access_service import (
    CareProviderAccessService,
)
from lib.services.care_provider_profile_service import (
    CareProviderProfileService,
)
from lib.services.reports import CGMReportService

from lib.services.cgm_upload_service import CGMUploadService
from lib.services.chat.chat_management_service import ChatManagementService
from lib.services.chat.chat_messaging_service import ChatMessagingService
from lib.services.chat.chat_notification_service import ChatNotificationService
from lib.services.chat.chat_participant_service import ChatParticipantService
from lib.services.support.support_ticket_service import SupportTicketService
from lib.services.chat.direct_chat_resolver import DirectChatResolver
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
from lib.services.dashboard_metrics.health_facility_metrics_service import (
    HealthFacilityMetricsService,
)
from lib.services.dashboard_metrics.package_metrics_service import (
    PackageMetricsService,
)
from lib.services.file_content_extractor import FileContentExtractorService
from lib.services.reports import FitnessReportService
from lib.services.fitness_upload_service import FitnessUploadService
from lib.services.vector import FitnessVectorService
from lib.services.health_facility_service import HealthFacilityService
from lib.services.libreview_service import LibreViewService
from lib.services.meal import MealService
from lib.services.reports import MealReportService
from lib.services.checkin_history_service import CheckinHistoryService
from lib.services.medication_service import MedicationService
from lib.services.exercise_service import ExerciseService
from lib.services.patient_workout_service import PatientWorkoutService
from lib.services.patient_facility_transfer_service import PatientFacilityTransferService
from lib.services.vector import MealVectorService
from lib.services.vector.medication import MedicationVectorService
from lib.services.prescription_extraction_service import PrescriptionExtractionService
from lib.services.consultation_extraction_service import ConsultationExtractionService
from lib.services.consultation_service import ConsultationService
from lib.services.package_service import PackageService
from lib.services.patient_connected_app_service import (
    PatientConnectedAppService,
)
from lib.services.patient_document_service import PatientDocumentService
from lib.services.patient_document_research_service import (
    PatientDocumentResearchService,
)
from lib.services.patient_package_assignment_service import (
    PatientPackageAssignmentService,
)
from lib.services.patient_diet_plan_service import PatientDietPlanService
from lib.services.patient_fitness_plan_service import PatientFitnessPlanService
from lib.services.patient_profile_service import PatientProfileService
from lib.services.profile_agent import ProfileAgentService
from lib.services.vector import PatientProfileVectorService
from lib.services.vector.plans import PlansVectorService
from lib.services.patient_sleep_service import PatientSleepService
from lib.services.patient_smbg_service import PatientSmbgService
from lib.services.patient_vital_service import PatientVitalService
from lib.services.patient_summary import PatientSummaryService
from lib.services.active_patient_service import ActivePatientService
from lib.services.patient_query_service import PatientQueryService
from lib.services.patient_enrichment_service import PatientEnrichmentService
from lib.services.patient_data_availability_service import (
    PatientDataAvailabilityService,
)
from lib.services.patient_daily_overview_service import PatientDailyOverviewService
from lib.services.patient_timeline_service import PatientTimelineService
from lib.services.day_view.resolver import DayViewService
from lib.services.progress.resolver import ProgressService
from lib.services.patient_data_export_service import PatientDataExportService
from lib.services.care_provider_query_service import CareProviderQueryService
from lib.services.package_query_service import PackageQueryService
from lib.services.osteoflag_service import OsteoFlagService

# Processors
from lib.services.reports import SleepReportService
from lib.services.vector import SMBGVectorService, WorkoutVectorService
from lib.services.vector.checkin import CheckinVectorService
from lib.services.daily_checkin_service import DailyCheckinService
from lib.services.sqs_service import SQSService
from lib.services.token_usage_service import TokenUsageService
from lib.services.user_device_service import UserDeviceService
from lib.services.reports import (
    FitnessStatsProcessor,
    CGMStatsProcessor,
    MealStatsProcessor,
    SleepStatsProcessor,
    SMBGStatsProcessor,
)
from lib.services.vector import CGMVectorService, VitalsVectorService


# AI Foundation
from lib.ai_foundation.config import settings as _ai_settings
from lib.ai_foundation.models.registry import ModelRegistry, ModelTask, build_default_registry
from lib.ai_foundation.models.circuit_breaker import CircuitBreaker
from lib.ai_foundation.models.gateway import ModelGateway
from lib.ai_foundation.translation import TranslationService
from lib.ai_foundation.prompts.registry import PromptRegistry
from lib.ai_foundation.memory.mongo_store import MongoMemoryStore
from lib.ai_foundation.retrieval.qdrant import QdrantRetriever
from lib.ai_foundation.cache.embedding_cache import EmbeddingCache
from lib.ai_foundation.events.bus import EventBus
from lib.ai_foundation.rate_limit.limiter import RateLimiter
from lib.ai_foundation.agents.core.patient_resolver import PatientNameResolver
from lib.ai_foundation.agents.core.context_loader import ContextLoader
from lib.ai_foundation.agents.core.persistence_service import PersistenceService
from lib.ai_foundation.agents.core.fact_extractor import FactExtractor
from lib.ai_foundation.agents.health_query.tools import ToolExecutor
from lib.ai_foundation.agents.health_query.planner import InvestigationPlanner
from lib.ai_foundation.agents.health_query.reflector import ReflectionEngine
from lib.ai_foundation.agents.health_query.reasoning_engine import ReasoningEngine
from lib.ai_foundation.agents.health_query.specialists import Specialist, GLUCOSE_SPEC, NUTRITION_SPEC, FITNESS_SPEC, VITALS_SPEC, SLEEP_SPEC, DOCUMENTS_SPEC
from lib.ai_foundation.agents.health_query.coordinator import Coordinator
from lib.ai_foundation.agents.health_query import HealthQueryAgent
from lib.ai_foundation.agents.research_agent import ResearchAgent
from lib.ai_foundation.agents.meal_analysis.agent import MealAnalysisAgent
from lib.ai_foundation.agents.meal_analysis.alternatives import (
    AlternativesEngine,
)
from lib.ai_foundation.agents.meal_analysis.context_loader import (
    MealContextLoader,
)
from lib.ai_foundation.agents.meal_analysis.extractor import MealExtractor
from lib.ai_foundation.agents.meal_analysis.glucose_predictor import (
    GlucosePredictor,
)
from lib.ai_foundation.agents.meal_analysis.scorer import MealScorer
from lib.ai_foundation.agents.proactive_monitor import ProactiveMonitorAgent
from lib.ai_foundation.agents.proactive_monitor.insight_tracker import InsightTracker
from lib.ai_foundation.agents.product_bot import ProductBotAgent
from lib.ai_foundation.agents.dashboard_help import DashboardHelpAgent
from lib.ai_foundation.rate_limit.public_limiter import PublicRateLimiter
from lib.ai_foundation.voice.config import voice_settings as _voice_settings
from lib.ai_foundation.voice.stt import BaseSpeechToText, build_stt
from lib.ai_foundation.voice.tts import BaseTextToSpeech, build_tts
from lib.ai_foundation.voice.orchestrator import VoiceOrchestrator
from lib.ai_foundation.clinical.metabolic.service import MetabolicService

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
    factory=lambda: cast(MongoStore, container.resolve(MongoStore)).get_collection(
        "cgm_reports"
    ),
    scope=Scope.singleton,
)
container.register(
    "fitness_report_collection",
    factory=lambda: cast(MongoStore, container.resolve(MongoStore)).get_collection(
        "fitness_reports"
    ),
    scope=Scope.singleton,
)
container.register(
    "sleep_report_collection",
    factory=lambda: cast(MongoStore, container.resolve(MongoStore)).get_collection(
        "sleep_reports"
    ),
    scope=Scope.singleton,
)
container.register(
    "meal_report_collection",
    factory=lambda: cast(MongoStore, container.resolve(MongoStore)).get_collection(
        "meal_reports"
    ),
    scope=Scope.singleton,
)
container.register(
    "patient_summary_collection",
    factory=lambda: cast(MongoStore, container.resolve(MongoStore)).get_collection(
        "patient_summaries"
    ),
    scope=Scope.singleton,
)
container.register(
    "chat_messages_collection",
    factory=lambda: cast(MongoStore, container.resolve(MongoStore)).get_collection(
        "chat_messages"
    ),
    scope=Scope.singleton,
)
container.register(
    "chats_collection",
    factory=lambda: cast(MongoStore, container.resolve(MongoStore)).get_collection(
        "chats"
    ),
    scope=Scope.singleton,
)
container.register(
    "patient_documents",
    factory=lambda: cast(MongoStore, container.resolve(MongoStore)).get_collection(
        "patient_documents"
    ),
)

container.register(
    "patient_document_summary_interactions_collection",
    factory=lambda: cast(MongoStore, container.resolve(MongoStore)).get_collection(
        "patient_document_summary_interactions"
    ),
    scope=Scope.singleton,
)

# Profile Agent Collection (unified onboarding + update)
container.register(
    "profile_agent_conversations_collection",
    factory=lambda: cast(MongoStore, container.resolve(MongoStore)).get_collection(
        "profile_agent_conversations"
    ),
    scope=Scope.singleton,
)




container.register(
    ArqTaskManager,
    lambda: get_arq_task_manager(),
    scope=Scope.singleton,
)


# CacheStore
for namespace in [
    "user_otp",
    "user_session",
    "fitness_sync",
    "patient_profile",
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

# 🔹 Support Tickets
container.register(SupportTicketService, SupportTicketService)
container.register(
    DirectChatResolver,
    lambda: DirectChatResolver(
        chat_service=cast(
            ChatManagementService, container.resolve(ChatManagementService)
        )
    ),
)


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

# 🔹 Patient Data Availability Service
container.register(
    PatientDataAvailabilityService,
    lambda: PatientDataAvailabilityService(
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
        clickhouse_store=cast(ClickHouseStore, container.resolve(ClickHouseStore)),
    ),
)

# 🔹 Patient Daily Overview Service
container.register(
    PatientDailyOverviewService,
    lambda: PatientDailyOverviewService(
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
        clickhouse_store=cast(ClickHouseStore, container.resolve(ClickHouseStore)),
        meal_report_service=cast(
            MealReportService, container.resolve(MealReportService)
        ),
        cgm_report_service=cast(CGMReportService, container.resolve(CGMReportService)),
        fitness_report_service=cast(
            FitnessReportService, container.resolve(FitnessReportService)
        ),
        sleep_report_service=cast(
            SleepReportService, container.resolve(SleepReportService)
        ),
    ),
)

# 🔹 Patient Timeline Service
container.register(
    PatientTimelineService,
    lambda: PatientTimelineService(
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
        clickhouse_store=cast(ClickHouseStore, container.resolve(ClickHouseStore)),
        insight_tracker=cast(InsightTracker, container.resolve(InsightTracker)),
        cgm_report_service=cast(CGMReportService, container.resolve(CGMReportService)),
        meal_report_service=cast(MealReportService, container.resolve(MealReportService)),
        fitness_report_service=cast(FitnessReportService, container.resolve(FitnessReportService)),
        sleep_report_service=cast(SleepReportService, container.resolve(SleepReportService)),
    ),
)

# 🔹 Day View Service (unified day timeline — compose on read)
container.register(
    DayViewService,
    lambda: DayViewService(
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
        clickhouse_store=cast(ClickHouseStore, container.resolve(ClickHouseStore)),
        cgm_report_service=cast(CGMReportService, container.resolve(CGMReportService)),
        meal_report_service=cast(MealReportService, container.resolve(MealReportService)),
        sleep_report_service=cast(SleepReportService, container.resolve(SleepReportService)),
        fitness_report_service=cast(FitnessReportService, container.resolve(FitnessReportService)),
        insight_tracker=cast(InsightTracker, container.resolve(InsightTracker)),
    ),
)

# 🔹 Progress Service (longitudinal trends — compose on read)
container.register(
    ProgressService,
    lambda: ProgressService(
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
        clickhouse_store=cast(ClickHouseStore, container.resolve(ClickHouseStore)),
        cgm_report_service=cast(CGMReportService, container.resolve(CGMReportService)),
        sleep_report_service=cast(SleepReportService, container.resolve(SleepReportService)),
        meal_report_service=cast(MealReportService, container.resolve(MealReportService)),
        fitness_report_service=cast(FitnessReportService, container.resolve(FitnessReportService)),
    ),
)

# 🔹 Patient Data Export Service
container.register(
    PatientDataExportService,
    lambda: PatientDataExportService(
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
        mongo_store=cast(MongoStore, container.resolve(MongoStore)),
        clickhouse_store=cast(ClickHouseStore, container.resolve(ClickHouseStore)),
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
        clickhouse_store=cast(ClickHouseStore, container.resolve(ClickHouseStore)),
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

# 🔹 Plans Vector Service
container.register(
    PlansVectorService,
    lambda: PlansVectorService(
        qdrant_store=cast(QdrantStore, container.resolve(QdrantStore)),
    ),
)

# 🔹 Patient Diet Plan Service
container.register(
    PatientDietPlanService,
    lambda: PatientDietPlanService(
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
        plans_vector_service=cast(PlansVectorService, container.resolve(PlansVectorService)),
        patient_profile_service=cast(PatientProfileService, container.resolve(PatientProfileService)),
    ),
)

# 🔹 Patient Fitness Plan Service
container.register(
    PatientFitnessPlanService,
    lambda: PatientFitnessPlanService(
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
        plans_vector_service=cast(PlansVectorService, container.resolve(PlansVectorService)),
        patient_profile_service=cast(PatientProfileService, container.resolve(PatientProfileService)),
    ),
)


# 🔹 Patient Document Service
container.register(
    PatientDocumentService,
    lambda: PatientDocumentService(
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

# 🔹 Patient Document Research Service
container.register(
    PatientDocumentResearchService,
    lambda: PatientDocumentResearchService(
        patient_document_collection=cast(
            MongoStore, container.resolve("patient_documents")
        ),
        patient_document_summary_interactions_collection=cast(
            MongoStore,
            container.resolve("patient_document_summary_interactions_collection"),
        ),
        patient_document_service=cast(
            PatientDocumentService, container.resolve(PatientDocumentService)
        ),
        medication_service=cast(
            MedicationService, container.resolve(MedicationService)
        ),
        token_usage_service=cast(
            TokenUsageService, container.resolve(TokenUsageService)
        ),
    ),
)


# 🔹 Meal Service
container.register(
    MealService,
    lambda: MealService(
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
        patient_profile_service=cast(
            PatientProfileService, container.resolve(PatientProfileService)
        ),
        meal_vector_service=cast(
            MealVectorService, container.resolve(MealVectorService)
        ),
    ),
)

# 🔹 Medication Vector Service
container.register(
    MedicationVectorService,
    lambda: MedicationVectorService(
        qdrant_store=cast(QdrantStore, container.resolve(QdrantStore)),
    ),
)

# 🔹 Prescription Extraction Service (v1 — ModelGateway + vision)
container.register(
    PrescriptionExtractionService,
    lambda: PrescriptionExtractionService(
        gateway=cast(ModelGateway, container.resolve(ModelGateway)),
    ),
)

# 🔹 Medication Service (v1)
container.register(
    MedicationService,
    lambda: MedicationService(
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
        medication_vector_service=cast(
            MedicationVectorService, container.resolve(MedicationVectorService),
        ),
    ),
)

# 🔹 Consultation Extraction Service (transcript → structured insights)
container.register(
    ConsultationExtractionService,
    lambda: ConsultationExtractionService(
        gateway=cast(ModelGateway, container.resolve(ModelGateway)),
    ),
)

# 🔹 Consultation Service (audio → S3 → STT → extraction → Mongo)
container.register(
    ConsultationService,
    lambda: ConsultationService(
        mongo_store=cast(MongoStore, container.resolve(MongoStore)),
        stt=cast(BaseSpeechToText, container.resolve(BaseSpeechToText)),
        extraction_service=cast(
            ConsultationExtractionService,
            container.resolve(ConsultationExtractionService),
        ),
    ),
)


# 🔹 Exercise Catalog Service
container.register(
    ExerciseService,
    lambda: ExerciseService(
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
    ),
)


# 🔹 Patient Workout Service
container.register(
    PatientWorkoutService,
    lambda: PatientWorkoutService(
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
    ),
)


# 🔹 Patient Facility Transfer Service
container.register(
    PatientFacilityTransferService,
    lambda: PatientFacilityTransferService(
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
    ),
)

# 🔹 Check-in History Service
container.register(
    CheckinHistoryService,
    lambda: CheckinHistoryService(
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
        clickhouse_store=cast(ClickHouseStore, container.resolve(ClickHouseStore)),
    ),
)

# 🔹 OsteoFlag Screening Service
container.register(
    OsteoFlagService,
    lambda: OsteoFlagService(
        token_usage_service=cast(
            TokenUsageService, container.resolve(TokenUsageService)
        ),
        patient_document_service=cast(
            PatientDocumentService, container.resolve(PatientDocumentService)
        ),
        osteoflag_detect_collection=cast(
            MongoStore, container.resolve("osteoflag_detect_collection")
        ),
        selected_ai_model="gpt-5.2",
    ),
)

# 🔹 Fitness Stats Processor
container.register(
    FitnessStatsProcessor,
    lambda: FitnessStatsProcessor(
        clickhouse_store=container.resolve(ClickHouseStore),
        postgres_store=container.resolve(PostgresStore),
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
        sleep_stats_processor=cast(
            SleepStatsProcessor, container.resolve(SleepStatsProcessor)
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
        patient_diet_plan_service=container.resolve(PatientDietPlanService),
        meal_report_service=container.resolve(MealReportService),
    ),
)

# 🔹 SMBG Stats Processor
container.register(
    SMBGStatsProcessor,
    lambda: SMBGStatsProcessor(
        postgres_store=container.resolve(PostgresStore),
        meal_stats_processor=container.resolve(MealStatsProcessor),
    ),
)


# 🔹 Sleep Stats Processor
container.register(
    SleepStatsProcessor,
    lambda: SleepStatsProcessor(
        clickhouse_store=cast(ClickHouseStore, container.resolve(ClickHouseStore)),
    ),
)

# 🔹 Sleep Report Service
container.register(
    SleepReportService,
    lambda: SleepReportService(
        sleep_report_collection=container.resolve("sleep_report_collection"),
        patient_summary_service=cast(
            PatientSummaryService, container.resolve(PatientSummaryService)
        ),
    ),
)

# 🔹 Fitness Report Service
container.register(
    FitnessReportService,
    lambda: FitnessReportService(
        fitness_report_collection=container.resolve("fitness_report_collection"),
        patient_summary_service=cast(
            PatientSummaryService, container.resolve(PatientSummaryService)
        ),
    ),
)

# 🔹 Meal Report Service
container.register(
    MealReportService,
    lambda: MealReportService(
        meal_report_collection=container.resolve("meal_report_collection"),
        patient_summary_service=cast(
            PatientSummaryService, container.resolve(PatientSummaryService)
        ),
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
        sleep_report_service=cast(
            SleepReportService, container.resolve(SleepReportService)
        ),
        patient_summary_service=cast(
            PatientSummaryService, container.resolve(PatientSummaryService)
        ),
    ),
)

# 🔹 Patient Summary Service
container.register(
    PatientSummaryService,
    lambda: PatientSummaryService(
        patient_summary_collection=container.resolve("patient_summary_collection"),
        fitness_reports_collection=container.resolve("fitness_report_collection"),
        sleep_reports_collection=container.resolve("sleep_report_collection"),
        meal_reports_collection=container.resolve("meal_report_collection"),
        cgm_reports_collection=container.resolve("cgm_report_collection"),
        token_usage_service=cast(
            TokenUsageService, container.resolve(TokenUsageService)
        ),
        clickhouse_store=cast(ClickHouseStore, container.resolve(ClickHouseStore)),
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

# 🔹 Patient Query Service
container.register(
    PatientQueryService,
    lambda: PatientQueryService(
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
    ),
)

# 🔹 Patient Enrichment Service
container.register(
    PatientEnrichmentService,
    lambda: PatientEnrichmentService(
        cgm_service=cast(
            CGMReportService,
            container.resolve(CGMReportService),
        ),
        user_device_service=cast(
            UserDeviceService,
            container.resolve(UserDeviceService),
        ),
    ),
)

# 🔹 Care Provider Query Service
container.register(
    CareProviderQueryService,
    lambda: CareProviderQueryService(
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
    ),
)

# 🔹 Care Provider Access Service
container.register(
    CareProviderAccessService,
    lambda: CareProviderAccessService(
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
    ),
)

# 🔹 Care Intent Service (provider-authored AI guidance)
container.register(
    CareIntentService,
    lambda: CareIntentService(
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
    ),
)

# 🔹 Package Query Service
container.register(
    PackageQueryService,
    lambda: PackageQueryService(
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
    ),
)

# 🔹 CGM Vector Service
container.register(
    CGMVectorService,
    lambda: CGMVectorService(
        qdrant_store=cast(QdrantStore, container.resolve(QdrantStore))
    ),
)

# 🔹 Fitness Vector Service
container.register(
    FitnessVectorService,
    lambda: FitnessVectorService(
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

# 🔹 Vitals Vector Service
container.register(
    VitalsVectorService,
    lambda: VitalsVectorService(
        qdrant_store=cast(QdrantStore, container.resolve(QdrantStore))
    ),
)


# 🔹 Workout Vector Service
container.register(
    WorkoutVectorService,
    lambda: WorkoutVectorService(
        qdrant_store=cast(QdrantStore, container.resolve(QdrantStore))
    ),
)


# 🔹 Checkin Vector Service
container.register(
    CheckinVectorService,
    lambda: CheckinVectorService(
        qdrant_store=cast(QdrantStore, container.resolve(QdrantStore))
    ),
)

# 🔹 Daily Checkin Service
container.register(
    DailyCheckinService,
    lambda: DailyCheckinService(
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
        checkin_vector_service=cast(
            CheckinVectorService, container.resolve(CheckinVectorService)
        ),
        patient_profile_service=cast(
            PatientProfileService, container.resolve(PatientProfileService)
        ),
    ),
)

# 🔹 Patient Notification Service
from lib.services.notifications.service import PatientNotificationService

container.register(
    PatientNotificationService,
    lambda: PatientNotificationService(
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
    ),
)

# 🔹 Patient Metrics Service
container.register(
    PatientMetricsService,
    lambda: PatientMetricsService(),
)

# 🔹 Active Patient Service
container.register(
    ActivePatientService,
    lambda: ActivePatientService(
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
    ),
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
        fitness_report_collection=container.resolve("fitness_report_collection")
    ),
)

# 🔹 Health Facility Metrics Service
container.register(
    HealthFacilityMetricsService,
    lambda: HealthFacilityMetricsService(),
)

# 🔹 Package Metrics Service
container.register(
    PackageMetricsService,
    lambda: PackageMetricsService(),
)


# 🔹 File Content Extractor Service
container.register(FileContentExtractorService, FileContentExtractorService)

# 🔹 Profile Agent Service (unified onboarding + update)
container.register(
    ProfileAgentService,
    lambda: ProfileAgentService(
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
        patient_profile_service=cast(
            PatientProfileService, container.resolve(PatientProfileService)
        ),
        conversation_collection=container.resolve(
            "profile_agent_conversations_collection"
        ),
    ),
)


# ═══════════════════════════════════════════════════════════════════════════
# AI Foundation Layer
# ═══════════════════════════════════════════════════════════════════════════


def _get_embed_fn():
    """Lazy import of embed_text to avoid circular imports at module level."""
    from lib.utils.vector_utils import embed_text
    return embed_text


def _build_prompt_registry() -> PromptRegistry:
    """Build a PromptRegistry with Langfuse backend (if enabled) + local fallback."""
    from pathlib import Path
    import logging
    from lib.ai_foundation.config import settings as _ai_settings

    # Initialize Langfuse client for prompt management (if enabled)
    langfuse_client = None
    if _ai_settings.LANGFUSE_ENABLED and _ai_settings.LANGFUSE_PUBLIC_KEY:
        try:
            from langfuse import Langfuse
            langfuse_client = Langfuse(
                public_key=_ai_settings.LANGFUSE_PUBLIC_KEY,
                secret_key=_ai_settings.LANGFUSE_SECRET_KEY,
                host=_ai_settings.LANGFUSE_HOST,
            )
            logging.getLogger(__name__).info("PromptRegistry: Langfuse backend enabled")
        except Exception as exc:
            logging.getLogger(__name__).warning("PromptRegistry: Langfuse init failed: %s", exc)

    registry = PromptRegistry(langfuse_client=langfuse_client)

    # Discover and register prompt directories for all foundation agents
    agents_dir = Path(__file__).parent.parent / "ai_foundation" / "agents"
    if agents_dir.exists():
        for agent_dir in agents_dir.iterdir():
            prompts_dir = agent_dir / "prompts"
            if prompts_dir.is_dir():
                try:
                    count = registry.register_directory(prompts_dir, namespace=agent_dir.name)
                    logging.getLogger(__name__).info(
                        "Registered %d prompts from %s", count, agent_dir.name,
                    )
                except Exception as e:
                    logging.getLogger(__name__).warning(
                        "Failed to load prompts from %s: %s", agent_dir.name, e,
                    )

    return registry


# CacheStore namespace for foundation services
container.register(
    "ai_foundation_cache",
    lambda: CacheStore(namespace="ai_foundation"),
    scope=Scope.singleton,
)

# Model Registry — central model configuration with fallback chains
container.register(
    ModelRegistry,
    lambda: build_default_registry(_ai_settings),
    scope=Scope.singleton,
)

# Circuit Breaker — provider failure detection
container.register(
    CircuitBreaker,
    lambda: CircuitBreaker(
        failure_threshold=_ai_settings.CIRCUIT_FAILURE_THRESHOLD,
        window_seconds=_ai_settings.CIRCUIT_WINDOW_SECONDS,
        cooldown_seconds=_ai_settings.CIRCUIT_COOLDOWN_SECONDS,
    ),
    scope=Scope.singleton,
)

# Model Gateway — unified LLM interface (complete, extract, stream)
# LiteLLM reads API keys from env vars (OPENAI_API_KEY, GEMINI_API_KEY) directly.
container.register(
    ModelGateway,
    lambda: ModelGateway(
        registry=cast(ModelRegistry, container.resolve(ModelRegistry)),
        circuit_breaker=cast(CircuitBreaker, container.resolve(CircuitBreaker)),
    ),
    scope=Scope.singleton,
)

# Prompt Registry — versioned prompt management (pre-loaded with agent prompts)
container.register(
    PromptRegistry,
    lambda: _build_prompt_registry(),
    scope=Scope.singleton,
)

# Translation Service — patient-facing text in the preferred AI language
container.register(
    TranslationService,
    lambda: TranslationService(
        gateway=cast(ModelGateway, container.resolve(ModelGateway)),
    ),
    scope=Scope.singleton,
)

# Memory Store — cross-agent patient facts and conversation turns
container.register(
    MongoMemoryStore,
    lambda: MongoMemoryStore(
        mongo_store=cast(MongoStore, container.resolve(MongoStore)),
    ),
    scope=Scope.singleton,
)

# Qdrant Retriever — semantic vector search
container.register(
    QdrantRetriever,
    lambda: QdrantRetriever(
        qdrant_store=cast(QdrantStore, container.resolve(QdrantStore)),
        collection_name=str(config("QDRANT_COLLECTION", default="patient_data")),
        embedding_fn=_get_embed_fn(),
        embedding_cache=cast(EmbeddingCache, container.resolve(EmbeddingCache)),
    ),
    scope=Scope.singleton,
)

# Embedding Cache — embedding vector cache
container.register(
    EmbeddingCache,
    lambda: EmbeddingCache(
        cache_store=container.resolve("ai_foundation_cache"),
        ttl_seconds=_ai_settings.EMBEDDING_CACHE_TTL,
    ),
    scope=Scope.singleton,
)

# Event Bus — agent-to-agent async pub/sub
container.register(
    EventBus,
    lambda: EventBus(),
    scope=Scope.singleton,
)

# Rate Limiter — per-tenant, priority-aware
container.register(
    RateLimiter,
    lambda: RateLimiter(
        cache_store=container.resolve("ai_foundation_cache"),
    ),
    scope=Scope.singleton,
)

# Metabolic Service — clinical metabolic engine (glucose prediction, attribution, BMIQ)
container.register(
    MetabolicService,
    lambda: MetabolicService(
        retriever=cast(QdrantRetriever, container.resolve(QdrantRetriever)),
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
        clickhouse_store=container.resolve(ClickHouseStore),
    ),
    scope=Scope.singleton,
)

# Patient Name Resolver — resolves UUIDs to display names for natural responses
container.register(
    PatientNameResolver,
    lambda: PatientNameResolver(
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
    ),
    scope=Scope.singleton,
)

# Health Query Agent v3 services
container.register(
    ContextLoader,
    lambda: ContextLoader(
        memory=cast(MongoMemoryStore, container.resolve(MongoMemoryStore)),
        patient_resolver=cast(PatientNameResolver, container.resolve(PatientNameResolver)),
        insight_tracker=cast(InsightTracker, container.resolve(InsightTracker)),
        gamification_service=cast(GamificationService, container.resolve(GamificationService)),
        retriever=cast(QdrantRetriever, container.resolve(QdrantRetriever)),
        care_intents=cast(CareIntentService, container.resolve(CareIntentService)),
    ),
    scope=Scope.singleton,
)


container.register(
    PersistenceService,
    lambda: PersistenceService(
        memory=cast(MongoMemoryStore, container.resolve(MongoMemoryStore)),
        gateway=cast(ModelGateway, container.resolve(ModelGateway)),
        cache_store=container.resolve("ai_foundation_cache"),
    ),
    scope=Scope.singleton,
)

container.register(
    FactExtractor,
    lambda: FactExtractor(
        memory=cast(MongoMemoryStore, container.resolve(MongoMemoryStore)),
        gateway=cast(ModelGateway, container.resolve(ModelGateway)),
    ),
    scope=Scope.singleton,
)

# Tool Executor + Reasoning Engine for agentic health query
container.register(
    ToolExecutor,
    lambda: ToolExecutor(
        qdrant=cast(QdrantRetriever, container.resolve(QdrantRetriever)),
        insight_tracker=cast(InsightTracker, container.resolve(InsightTracker)),
        patient_resolver=cast(PatientNameResolver, container.resolve(PatientNameResolver)),
        metabolic_service=cast(MetabolicService, container.resolve(MetabolicService)),
    ),
    scope=Scope.singleton,
)

container.register(
    InvestigationPlanner,
    lambda: InvestigationPlanner(
        gateway=cast(ModelGateway, container.resolve(ModelGateway)),
    ),
    scope=Scope.singleton,
)

container.register(
    ReflectionEngine,
    lambda: ReflectionEngine(
        gateway=cast(ModelGateway, container.resolve(ModelGateway)),
    ),
    scope=Scope.singleton,
)

container.register(
    ReasoningEngine,
    lambda: ReasoningEngine(
        gateway=cast(ModelGateway, container.resolve(ModelGateway)),
        tool_executor=cast(ToolExecutor, container.resolve(ToolExecutor)),
        planner=cast(InvestigationPlanner, container.resolve(InvestigationPlanner)),
        reflector=cast(ReflectionEngine, container.resolve(ReflectionEngine)),
    ),
    scope=Scope.singleton,
)

# Domain specialists for multi-agent coordination
def _build_specialists() -> dict[str, Specialist]:
    gw = cast(ModelGateway, container.resolve(ModelGateway))
    te = cast(ToolExecutor, container.resolve(ToolExecutor))
    return {
        "glucose": Specialist(domain_spec=GLUCOSE_SPEC, gateway=gw, tool_executor=te),
        "nutrition": Specialist(domain_spec=NUTRITION_SPEC, gateway=gw, tool_executor=te),
        "fitness": Specialist(domain_spec=FITNESS_SPEC, gateway=gw, tool_executor=te),
        "vitals": Specialist(domain_spec=VITALS_SPEC, gateway=gw, tool_executor=te),
        "sleep": Specialist(domain_spec=SLEEP_SPEC, gateway=gw, tool_executor=te),
        "documents": Specialist(domain_spec=DOCUMENTS_SPEC, gateway=gw, tool_executor=te),
    }

container.register(
    Coordinator,
    lambda: Coordinator(
        gateway=cast(ModelGateway, container.resolve(ModelGateway)),
        tool_executor=cast(ToolExecutor, container.resolve(ToolExecutor)),
        planner=cast(InvestigationPlanner, container.resolve(InvestigationPlanner)),
        reflector=cast(ReflectionEngine, container.resolve(ReflectionEngine)),
        specialists=_build_specialists(),
    ),
    scope=Scope.singleton,
)

# Health Query Agent v3 — multi-agent orchestrator
container.register(
    HealthQueryAgent,
    lambda: HealthQueryAgent(
        gateway=cast(ModelGateway, container.resolve(ModelGateway)),
        memory=cast(MongoMemoryStore, container.resolve(MongoMemoryStore)),
        prompts=cast(PromptRegistry, container.resolve(PromptRegistry)),
        event_bus=cast(EventBus, container.resolve(EventBus)),
        context_loader=cast(ContextLoader, container.resolve(ContextLoader)),
        reasoning_engine=cast(ReasoningEngine, container.resolve(ReasoningEngine)),
        coordinator=cast(Coordinator, container.resolve(Coordinator)),
        persistence=cast(PersistenceService, container.resolve(PersistenceService)),
        fact_extractor=cast(FactExtractor, container.resolve(FactExtractor)),
        translator=cast(TranslationService, container.resolve(TranslationService)),
    ),
    scope=Scope.singleton,
)

# Research Agent v1 — cohort-scale provider analytics
container.register(
    ResearchAgent,
    lambda: ResearchAgent(
        gateway=cast(ModelGateway, container.resolve(ModelGateway)),
        mongo_store=cast(MongoStore, container.resolve(MongoStore)),
        qdrant_store=cast(QdrantStore, container.resolve(QdrantStore)),
        memory=cast(MongoMemoryStore, container.resolve(MongoMemoryStore)),
        prompts=cast(PromptRegistry, container.resolve(PromptRegistry)),
        event_bus=cast(EventBus, container.resolve(EventBus)),
        embed_fn=_get_embed_fn(),
        patient_name_resolver=cast(PatientNameResolver, container.resolve(PatientNameResolver)),
    ),
    scope=Scope.singleton,
)

# Insight Tracker — dedup + escalation for proactive monitor
container.register(
    InsightTracker,
    lambda: InsightTracker(
        mongo_store=cast(MongoStore, container.resolve(MongoStore)),
    ),
    scope=Scope.singleton,
)

# Proactive Monitor Agent — background health scanning (direct Qdrant fetch)
container.register(
    ProactiveMonitorAgent,
    lambda: ProactiveMonitorAgent(
        gateway=cast(ModelGateway, container.resolve(ModelGateway)),
        qdrant=cast(QdrantRetriever, container.resolve(QdrantRetriever)),
        memory=cast(MongoMemoryStore, container.resolve(MongoMemoryStore)),
        event_bus=cast(EventBus, container.resolve(EventBus)),
        insight_tracker=cast(InsightTracker, container.resolve(InsightTracker)),
        metabolic_service=cast(MetabolicService, container.resolve(MetabolicService)),
        care_intents=cast(CareIntentService, container.resolve(CareIntentService)),
        daily_tasks=cast(GamificationService, container.resolve(GamificationService)),
        health_agent=cast(HealthQueryAgent, container.resolve(HealthQueryAgent)),
    ),
    scope=Scope.singleton,
)

# ═══════════════════════════════════════════════════════════════════════════
# 🍽️ Meal Analysis Agent — preview-first pipeline
# ═══════════════════════════════════════════════════════════════════════════

container.register(
    MealContextLoader,
    lambda: MealContextLoader(
        qdrant_retriever=cast(QdrantRetriever, container.resolve(QdrantRetriever)),
        memory_store=cast(
            MongoMemoryStore, container.resolve(MongoMemoryStore)
        ),
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
    ),
    scope=Scope.singleton,
)

container.register(
    MealExtractor,
    lambda: MealExtractor(
        gateway=cast(ModelGateway, container.resolve(ModelGateway)),
        prompt_registry=cast(PromptRegistry, container.resolve(PromptRegistry)),
    ),
    scope=Scope.singleton,
)

# Scorer/alternatives/glucose send text-only JSON — MEAL_REASONING routes them
# to a text model instead of paying vision (gpt-4o) pricing. Only the
# extractor sees the photo and stays on MEAL_ANALYSIS.
container.register(
    MealScorer,
    lambda: MealScorer(
        gateway=cast(ModelGateway, container.resolve(ModelGateway)),
        prompt_registry=cast(PromptRegistry, container.resolve(PromptRegistry)),
        model_task=ModelTask.MEAL_REASONING,
    ),
    scope=Scope.singleton,
)

container.register(
    AlternativesEngine,
    lambda: AlternativesEngine(
        gateway=cast(ModelGateway, container.resolve(ModelGateway)),
        prompt_registry=cast(PromptRegistry, container.resolve(PromptRegistry)),
        model_task=ModelTask.MEAL_REASONING,
    ),
    scope=Scope.singleton,
)

container.register(
    GlucosePredictor,
    lambda: GlucosePredictor(
        gateway=cast(ModelGateway, container.resolve(ModelGateway)),
        prompt_registry=cast(PromptRegistry, container.resolve(PromptRegistry)),
        model_task=ModelTask.MEAL_REASONING,
    ),
    scope=Scope.singleton,
)

container.register(
    MealAnalysisAgent,
    lambda: MealAnalysisAgent(
        gateway=cast(ModelGateway, container.resolve(ModelGateway)),
        qdrant_retriever=cast(QdrantRetriever, container.resolve(QdrantRetriever)),
        context_loader=cast(MealContextLoader, container.resolve(MealContextLoader)),
        extractor=cast(MealExtractor, container.resolve(MealExtractor)),
        scorer=cast(MealScorer, container.resolve(MealScorer)),
        alternatives=cast(AlternativesEngine, container.resolve(AlternativesEngine)),
        glucose_predictor=cast(
            GlucosePredictor, container.resolve(GlucosePredictor)
        ),
        metabolic_service=cast(MetabolicService, container.resolve(MetabolicService)),
        memory=cast(MongoMemoryStore, container.resolve(MongoMemoryStore)),
        prompts=cast(PromptRegistry, container.resolve(PromptRegistry)),
        event_bus=cast(EventBus, container.resolve(EventBus)),
    ),
    scope=Scope.singleton,
)

# ═══════════════════════════════════════════════════════════════════════════
# 🎙️ Voice Agent Services
# ═══════════════════════════════════════════════════════════════════════════

container.register(
    BaseSpeechToText,
    lambda: build_stt(settings=_voice_settings),
    scope=Scope.singleton,
)

container.register(
    BaseTextToSpeech,
    lambda: build_tts(settings=_voice_settings),
    scope=Scope.singleton,
)

async def _upload_voice_audio(patient_id: str, audio_bytes: bytes) -> str | None:
    """Upload voice audio to S3 — wired into VoiceOrchestrator via DI.

    Audio arrives as raw PCM 16-bit 16kHz mono from the WebSocket session.
    We wrap it in a WAV container so the stored file is playable.
    """
    import asyncio
    import io
    import wave
    from uuid import uuid4
    from lib.utils.s3_utils import upload_file_to_s3

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(_voice_settings.INPUT_SAMPLE_RATE)
        wf.writeframes(audio_bytes)
    wav_bytes = buf.getvalue()

    return await asyncio.to_thread(
        upload_file_to_s3,
        file_bytes=wav_bytes,
        bucket_name="user-assets.aihealth.clinic",
        file_name=f"{uuid4()}.wav",
        content_type="audio/wav",
        folder_path=f"patients/{patient_id}/voice/audio",
    )

container.register(
    VoiceOrchestrator,
    lambda: VoiceOrchestrator(
        stt=cast(BaseSpeechToText, container.resolve(BaseSpeechToText)),
        tts=cast(BaseTextToSpeech, container.resolve(BaseTextToSpeech)),
        agent=cast(HealthQueryAgent, container.resolve(HealthQueryAgent)),
        patient_resolver=cast(PatientNameResolver, container.resolve(PatientNameResolver)),
        settings=_voice_settings,
        upload_audio=_upload_voice_audio,
        translation=cast(TranslationService, container.resolve(TranslationService)),
    ),
    scope=Scope.singleton,
)

# 🔹 Workout Voice Service
from lib.services.workout_voice_service import WorkoutVoiceService

container.register(
    WorkoutVoiceService,
    lambda: WorkoutVoiceService(
        gateway=cast(ModelGateway, container.resolve(ModelGateway)),
        stt=cast(BaseSpeechToText, container.resolve(BaseSpeechToText)),
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
    ),
    scope=Scope.singleton,
)

# ═══════════════════════════════════════════════════════════════════════════
# 🎮 Gamification Services
# ═══════════════════════════════════════════════════════════════════════════

from lib.services.gamification.xp_service import XPService
from lib.services.gamification.streak_service import StreakService
from lib.services.gamification.task_generator import TaskGeneratorService
from lib.services.gamification.achievement_evaluator import AchievementEvaluator
from lib.services.gamification.event_handler import GamificationEventHandler
from lib.services.gamification.service import GamificationService
from lib.services.gamification.buddy_service import BuddyService
from lib.services.gamification.group_service import GroupService
from lib.services.gamification.challenge_service import ChallengeService
from lib.services.gamification.leaderboard_service import LeaderboardService
from lib.services.gamification.feed_service import FeedService
from lib.services.gamification.care_provider_service import CPGamificationService

container.register(
    XPService,
    lambda: XPService(
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
    ),
)
container.register(
    StreakService,
    lambda: StreakService(
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
    ),
)
container.register(
    TaskGeneratorService,
    lambda: TaskGeneratorService(
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
    ),
)
container.register(
    AchievementEvaluator,
    lambda: AchievementEvaluator(
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
        xp_service=cast(XPService, container.resolve(XPService)),
    ),
)
container.register(
    GamificationEventHandler,
    lambda: GamificationEventHandler(
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
        xp_service=cast(XPService, container.resolve(XPService)),
        achievement_evaluator=cast(AchievementEvaluator, container.resolve(AchievementEvaluator)),
    ),
)
container.register(
    GamificationService,
    lambda: GamificationService(
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
        xp_service=cast(XPService, container.resolve(XPService)),
        task_generator=cast(TaskGeneratorService, container.resolve(TaskGeneratorService)),
        achievement_evaluator=cast(AchievementEvaluator, container.resolve(AchievementEvaluator)),
    ),
)
container.register(
    BuddyService,
    lambda: BuddyService(
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
    ),
)
container.register(
    GroupService,
    lambda: GroupService(
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
    ),
)
container.register(
    ChallengeService,
    lambda: ChallengeService(
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
        xp_service=cast(XPService, container.resolve(XPService)),
    ),
)
container.register(
    LeaderboardService,
    lambda: LeaderboardService(
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
    ),
)
container.register(
    FeedService,
    lambda: FeedService(
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
        xp_service=cast(XPService, container.resolve(XPService)),
    ),
)
container.register(
    CPGamificationService,
    lambda: CPGamificationService(
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
    ),
)


# ═══════════════════════════════════════════════════════════════════════════
# 🔌 EventBus subscriptions
# ═══════════════════════════════════════════════════════════════════════════


def _subscribe_event_handlers() -> None:
    """Wire domain handlers to EventBus events."""
    import logging
    from uuid import UUID as _UUID

    from lib.ai_foundation.events.bus import EventBus as _EventBus
    from lib.ai_foundation.events.schemas import HealthEvent as _HealthEvent
    from lib.ai_foundation.events.schemas import HealthEventType as _HealthEventType

    bus = cast(_EventBus, container.resolve(_EventBus))
    gamification = cast(
        GamificationEventHandler,
        container.resolve(GamificationEventHandler),
    )

    async def _on_meal_logged(event: _HealthEvent) -> None:
        try:
            await gamification.on_meal_logged(_UUID(event.patient_id))
        except Exception:
            logging.getLogger(__name__).exception(
                "gamification.on_meal_logged failed for %s", event.patient_id
            )

    bus.subscribe([_HealthEventType.MEAL_LOGGED.value], _on_meal_logged)


_subscribe_event_handlers()


# ═══════════════════════════════════════════════════════════════════════════
# 🤖 Product Bot Agent — public-facing website chatbot
# ═══════════════════════════════════════════════════════════════════════════

container.register(
    "product_bot_cache",
    lambda: CacheStore(namespace="product_bot"),
    scope=Scope.singleton,
)

container.register(
    "product_bot_conversations_collection",
    factory=lambda: cast(MongoStore, container.resolve(MongoStore)).get_collection(
        "product_bot_conversations"
    ),
    scope=Scope.singleton,
)

container.register(
    PublicRateLimiter,
    lambda: PublicRateLimiter(
        cache_store=container.resolve("product_bot_cache"),
    ),
    scope=Scope.singleton,
)

container.register(
    ProductBotAgent,
    lambda: ProductBotAgent(
        gateway=cast(ModelGateway, container.resolve(ModelGateway)),
        memory=cast(MongoMemoryStore, container.resolve(MongoMemoryStore)),
        prompts=cast(PromptRegistry, container.resolve(PromptRegistry)),
        event_bus=cast(EventBus, container.resolve(EventBus)),
        cache_store=container.resolve("product_bot_cache"),
        analytics_collection=container.resolve("product_bot_conversations_collection"),
    ),
    scope=Scope.singleton,
)

container.register(
    DashboardHelpAgent,
    lambda: DashboardHelpAgent(
        gateway=cast(ModelGateway, container.resolve(ModelGateway)),
    ),
    scope=Scope.singleton,
)
