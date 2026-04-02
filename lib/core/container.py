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
from lib.services.meal import MealAnalysisService, MealService
from lib.services.reports import MealReportService
from lib.services.vector import MealVectorService
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
from lib.services.profile_update_agent import ProfileUpdateAgentService
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
from lib.services.patient_data_export_service import PatientDataExportService
from lib.services.care_provider_query_service import CareProviderQueryService
from lib.services.package_query_service import PackageQueryService
from lib.services.osteoflag_service import OsteoFlagService

# Processors
from lib.services.prescription_analysis_service import (
    PrescriptionAnalysisService,
)
from lib.services.prescription_service import PrescriptionService
from lib.services.qdrant_search_engine.qdrant_search_engine import (
    QdrantSearchEngine,
)
from lib.services.reports import SleepReportService
from lib.services.vector import SMBGVectorService
from lib.services.vector.checkin import CheckinVectorService
from lib.services.daily_checkin_service import DailyCheckinService
from lib.services.sqs_service import SQSService
from lib.services.token_usage_service import TokenUsageService
from lib.services.user_device_service import UserDeviceService
from lib.services.weightloss_agent.analytics_service import AnalyticsService
from lib.services.reports import (
    FitnessStatsProcessor,
    CGMStatsProcessor,
    MealStatsProcessor,
    SleepStatsProcessor,
    SMBGStatsProcessor,
)
from lib.services.vector import CGMVectorService, VitalsVectorService

# Weight Loss Agent Service
from lib.services.weight_loss_agent_service import WeightLossAgentService
from lib.services.weightloss_agent.intake_service import IntakeService
from lib.services.weightloss_agent.safety_rules_service import (
    SafetyRulesService,
)
from lib.services.weightloss_agent.plan_composer_service import (
    PlanComposerService,
)
from lib.services.weightloss_agent.glp1_symptoms_service import (
    Glp1SymptomsService,
)
from lib.services.weightloss_agent.glp1_injection_service import (
    Glp1InjectionService,
)
from lib.services.weightloss_agent.exercise_recommendation_service import (
    ExerciseRecommendationService,
)
from lib.services.weightloss_agent.coach_messenger_service import (
    CoachMessengerService,
)
from lib.services.weightloss_agent.flow_engine import FlowEngine
from lib.services.weightloss_agent.task_service import TaskService
from lib.services.weightloss_agent.agentic_chat_service import (
    AgenticChatService,
)
from lib.services.weightloss_agent.agentic_orchestrator import (
    AgenticOrchestrator,
)

from lib.services.health_query_agent.service import HealthQueryAgentService

# AI Foundation
from lib.ai_foundation.config import settings as _ai_settings
from lib.ai_foundation.models.registry import ModelRegistry, build_default_registry
from lib.ai_foundation.models.circuit_breaker import CircuitBreaker
from lib.ai_foundation.models.gateway import ModelGateway
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
from lib.ai_foundation.agents.proactive_monitor import ProactiveMonitorAgent
from lib.ai_foundation.agents.proactive_monitor.insight_tracker import InsightTracker

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
    "ai_conversation_messages_collection",
    factory=lambda: cast(MongoStore, container.resolve(MongoStore)).get_collection(
        "ai_conversation_messages"
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

# Weight Loss Agent Collections
container.register(
    "inbody_reports_collection",
    factory=lambda: cast(MongoStore, container.resolve(MongoStore)).get_collection(
        "wtloss_inbody_reports"
    ),
    scope=Scope.singleton,
)
container.register(
    "weight_loss_interactions_collection",
    factory=lambda: cast(MongoStore, container.resolve(MongoStore)).get_collection(
        "wtloss_weight_loss_interactions"
    ),
    scope=Scope.singleton,
)
container.register(
    "weight_loss_progress_analyses_collection",
    factory=lambda: cast(MongoStore, container.resolve(MongoStore)).get_collection(
        "wtloss_weight_loss_progress_analyses"
    ),
    scope=Scope.singleton,
)

# Profile Update Agent Collection
container.register(
    "profile_update_conversations_collection",
    factory=lambda: cast(MongoStore, container.resolve(MongoStore)).get_collection(
        "profile_update_conversations"
    ),
    scope=Scope.singleton,
)


# Intake + patient app collections
container.register(
    "exercise_preferences_collection",
    factory=lambda: cast(MongoStore, container.resolve(MongoStore)).get_collection(
        "wtloss_exercise_preferences"
    ),
    scope=Scope.singleton,
)
container.register(
    "fitness_screen_collection",
    factory=lambda: cast(MongoStore, container.resolve(MongoStore)).get_collection(
        "wtloss_fitness_screen"
    ),
    scope=Scope.singleton,
)
container.register(
    "willingness_commitment_collection",
    factory=lambda: cast(MongoStore, container.resolve(MongoStore)).get_collection(
        "wtloss_willingness_commitment"
    ),
    scope=Scope.singleton,
)
container.register(
    "plan_snapshots_collection",
    factory=lambda: cast(MongoStore, container.resolve(MongoStore)).get_collection(
        "wtloss_plan_snapshots"
    ),
    scope=Scope.singleton,
)
container.register(
    "weightloss_flow_instances_collection",
    factory=lambda: cast(MongoStore, container.resolve(MongoStore)).get_collection(
        "wtloss_flow_instances"
    ),
    scope=Scope.singleton,
)
container.register(
    "weightloss_tasks_collection",
    factory=lambda: cast(MongoStore, container.resolve(MongoStore)).get_collection(
        "wtloss_tasks"
    ),
    scope=Scope.singleton,
)
container.register(
    "weightloss_glp_injection_collection",
    factory=lambda: cast(MongoStore, container.resolve(MongoStore)).get_collection(
        "wtloss_glpinjection_login"
    ),
    scope=Scope.singleton,
)
container.register(
    "weightloss_symptom_daily_collection",
    factory=lambda: cast(MongoStore, container.resolve(MongoStore)).get_collection(
        "wtloss_symptom_daily"
    ),
    scope=Scope.singleton,
)
container.register(
    "suggestion_cards_collection",
    factory=lambda: cast(MongoStore, container.resolve(MongoStore)).get_collection(
        "wtloss_suggestion_cards"
    ),
    scope=Scope.singleton,
)
container.register(
    "weekly_symptoms_glp1_collection",
    factory=lambda: cast(MongoStore, container.resolve(MongoStore)).get_collection(
        "wtloss_weekly_symptoms_glp1"
    ),
    scope=Scope.singleton,
)
container.register(
    "audit_traces_collection",
    factory=lambda: cast(MongoStore, container.resolve(MongoStore)).get_collection(
        "wtloss_audit_traces"
    ),
    scope=Scope.singleton,
)
container.register(
    "analytics_events_collection",
    factory=lambda: cast(MongoStore, container.resolve(MongoStore)).get_collection(
        "wtloss_analytics_events"
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
    "health_query_agent",
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
        prescription_service=cast(
            PrescriptionService, container.resolve(PrescriptionService)
        ),
        weight_loss_agent_service=cast(
            WeightLossAgentService, container.resolve(WeightLossAgentService)
        ),
        token_usage_service=cast(
            TokenUsageService, container.resolve(TokenUsageService)
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

# 🔹 Meal Service
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
    lambda: FitnessStatsProcessor(clickhouse_store=container.resolve(ClickHouseStore)),
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

# 🔹 Weight Loss Agent Service (MongoDB)
container.register(
    AnalyticsService,
    lambda: AnalyticsService(
        audit_traces_collection=cast(
            MongoStore, container.resolve("audit_traces_collection")
        ),
        analytics_events_collection=cast(
            MongoStore, container.resolve("analytics_events_collection")
        ),
    ),
)

# 🔹 Intake Service
container.register(
    IntakeService,
    lambda: IntakeService(
        exercise_preferences_collection=container.resolve(
            "exercise_preferences_collection"
        ),
        fitness_screen_collection=container.resolve("fitness_screen_collection"),
        willingness_commitment_collection=container.resolve(
            "willingness_commitment_collection"
        ),
        analytics_service=cast(AnalyticsService, container.resolve(AnalyticsService)),
    ),
)

# 🔹 Safety Rules Service
container.register(
    SafetyRulesService,
    lambda: SafetyRulesService(
        analytics_service=cast(AnalyticsService, container.resolve(AnalyticsService)),
    ),
)

# 🔹 Exercise Recommendation Service
container.register(
    ExerciseRecommendationService,
    lambda: ExerciseRecommendationService(
        ai_conversation_service=cast(
            AiConversationService, container.resolve(AiConversationService)
        ),
    ),
)

# 🔹 Plan Composer Service
container.register(
    PlanComposerService,
    lambda: PlanComposerService(
        plan_snapshots_collection=container.resolve("plan_snapshots_collection"),
        inbody_reports_collection=container.resolve("inbody_reports_collection"),
        intake_service=cast(IntakeService, container.resolve(IntakeService)),
        safety_rules_service=cast(
            SafetyRulesService, container.resolve(SafetyRulesService)
        ),
        analytics_service=cast(AnalyticsService, container.resolve(AnalyticsService)),
        exercise_recommendation_service=cast(
            ExerciseRecommendationService,
            container.resolve(ExerciseRecommendationService),
        ),
        ai_conversation_service=cast(
            AiConversationService, container.resolve(AiConversationService)
        ),
    ),
)

# 🔹 GLP-1 Symptoms Service
container.register(
    Glp1SymptomsService,
    lambda: Glp1SymptomsService(
        weekly_symptoms_collection=container.resolve("weekly_symptoms_glp1_collection"),
        analytics_service=cast(AnalyticsService, container.resolve(AnalyticsService)),
    ),
)

# 🔹 GLP-1 Injection Settings Service
container.register(
    Glp1InjectionService,
    lambda: Glp1InjectionService(
        settings_collection=container.resolve("weightloss_glp_injection_collection"),
    ),
)

# 🔹 Weightloss Flow Engine
container.register(
    FlowEngine,
    lambda: FlowEngine(
        flow_collection=container.resolve("weightloss_flow_instances_collection")
    ),
)

# 🔹 Weightloss Task Service
container.register(
    TaskService,
    lambda: TaskService(
        tasks_collection=container.resolve("weightloss_tasks_collection")
    ),
)

# 🔹 Coach Messenger Service
container.register(
    CoachMessengerService,
    lambda: CoachMessengerService(
        suggestion_cards_collection=container.resolve("suggestion_cards_collection"),
        plan_composer_service=cast(
            PlanComposerService, container.resolve(PlanComposerService)
        ),
        analytics_service=cast(AnalyticsService, container.resolve(AnalyticsService)),
        ai_conversation_service=cast(
            AiConversationService, container.resolve(AiConversationService)
        ),
    ),
)

# 🔹 Agentic Orchestrator
container.register(
    AgenticOrchestrator,
    lambda: AgenticOrchestrator(
        plan_composer_service=cast(
            PlanComposerService, container.resolve(PlanComposerService)
        ),
        coach_messenger_service=cast(
            CoachMessengerService, container.resolve(CoachMessengerService)
        ),
        analytics_service=cast(AnalyticsService, container.resolve(AnalyticsService)),
    ),
)

container.register(
    WeightLossAgentService,
    lambda: WeightLossAgentService(
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
        clickhouse_store=cast(ClickHouseStore, container.resolve(ClickHouseStore)),
        reports_collection=cast(
            MongoStore, container.resolve("inbody_reports_collection")
        ),
        interactions_collection=cast(
            MongoStore,
            container.resolve("weight_loss_interactions_collection"),
        ),
        progress_analyses_collection=cast(
            MongoStore,
            container.resolve("weight_loss_progress_analyses_collection"),
        ),
        patient_profile_service=cast(
            PatientProfileService, container.resolve(PatientProfileService)
        ),
        care_provider_profile_service=cast(
            CareProviderProfileService,
            container.resolve(CareProviderProfileService),
        ),
        analytics_service=cast(AnalyticsService, container.resolve(AnalyticsService)),
        token_usage_service=cast(
            TokenUsageService, container.resolve(TokenUsageService)
        ),
    ),
)

# 🔹 Agentic Weightloss Chat Service
container.register(
    AgenticChatService,
    lambda: AgenticChatService(
        mongo_store=cast(MongoStore, container.resolve(MongoStore)),
        flow_engine=cast(FlowEngine, container.resolve(FlowEngine)),
        task_service=cast(TaskService, container.resolve(TaskService)),
        injection_service=cast(
            Glp1InjectionService, container.resolve(Glp1InjectionService)
        ),
        intake_service=cast(IntakeService, container.resolve(IntakeService)),
        safety_rules_service=cast(
            SafetyRulesService, container.resolve(SafetyRulesService)
        ),
        chat_messaging_service=cast(
            ChatMessagingService, container.resolve(ChatMessagingService)
        ),
        plan_composer_service=cast(
            PlanComposerService, container.resolve(PlanComposerService)
        ),
        weight_loss_agent_service=cast(
            WeightLossAgentService, container.resolve(WeightLossAgentService)
        ),
        patient_profile_service=cast(
            PatientProfileService, container.resolve(PatientProfileService)
        ),
        symptom_daily_collection=container.resolve(
            "weightloss_symptom_daily_collection"
        ),
        glp1_symptoms_service=cast(
            Glp1SymptomsService, container.resolve(Glp1SymptomsService)
        ),
        coach_messenger_service=cast(
            CoachMessengerService, container.resolve(CoachMessengerService)
        ),
        suggestion_cards_collection=container.resolve("suggestion_cards_collection"),
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
    ),
)

# 🔹 Qdrant Search Engine
container.register(
    QdrantSearchEngine,
    lambda: QdrantSearchEngine(
        qdrant_store=cast(QdrantStore, container.resolve(QdrantStore)),
    ),
)

# 🔹 Health Query Agent Service
container.register(
    HealthQueryAgentService,
    lambda: HealthQueryAgentService(
        qdrant_store=cast(QdrantStore, container.resolve(QdrantStore)),
        mongo_store=cast(MongoStore, container.resolve(MongoStore)),
        cache_store=cast(CacheStore, container.resolve("health_query_agent")),
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
        patient_profile_store=cast(CacheStore, container.resolve("patient_profile")),
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

# 🔹 Profile Update Agent Service
container.register(
    ProfileUpdateAgentService,
    lambda: ProfileUpdateAgentService(
        postgres_store=cast(PostgresStore, container.resolve(PostgresStore)),
        patient_profile_service=cast(
            PatientProfileService, container.resolve(PatientProfileService)
        ),
        conversation_collection=container.resolve(
            "profile_update_conversations_collection"
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

    # Also register existing health_query_agent prompts/playbooks for backward compat
    legacy_prompts = Path(__file__).parent.parent / "services" / "health_query_agent" / "prompts"
    if legacy_prompts.is_dir():
        try:
            registry.register_directory(legacy_prompts, namespace="health_query_legacy")
        except Exception:
            pass

    legacy_playbooks = Path(__file__).parent.parent / "services" / "health_query_agent" / "v2" / "playbooks"
    if legacy_playbooks.is_dir():
        try:
            registry.register_directory(legacy_playbooks, namespace="health_query_legacy.playbooks")
        except Exception:
            pass

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
    lambda: build_default_registry(),
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
    ),
    scope=Scope.singleton,
)
