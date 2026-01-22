from typing import cast

from lib.core.cache_store import CacheStore
from lib.core.container import container
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
from lib.services.care_provider_profile_service import (
    CareProviderProfileService,
)
from lib.services.cgm_report_service import CGMReportService

from lib.services.cgm_vector_service import (
    CGMVectorService,
)
from lib.services.cgm_upload_service import CGMUploadService
from lib.services.chat.chat_management_service import ChatManagementService
from lib.services.chat.chat_messaging_service import ChatMessagingService
from lib.services.chat.chat_notification_service import ChatNotificationService
from lib.services.dashboard_metrics.cgm_metrics_service import (
    CGMMetricsService,
)
from lib.services.dashboard_metrics.fitneess_metrics_service import (
    FitnessMetricsService,
)
from lib.services.dashboard_metrics.meal_metrics_service import (
    MealMetricsService,
)
from lib.services.dashboard_metrics.smbg_metrics_service import (
    SMBGMetricsService,
)
from lib.services.dashboard_metrics.patient_metrics_service import (
    PatientMetricsService,
)
from lib.services.dashboard_metrics.health_facility_metrics_service import (
    HealthFacilityMetricsService,
)
from lib.services.dashboard_metrics.package_metrics_service import (
    PackageMetricsService,
)
from lib.services.file_content_extractor import FileContentExtractorService
from lib.services.fitness_report_service import FitnessReportService
from lib.services.fitness_upload_service import FitnessUploadService
from lib.services.fitness_vector_service.fitness_vector_service import (
    FitnessVectorService,
)
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
from lib.services.patient_document_research_service import (
    PatientDocumentResearchService,
)
from lib.services.patient_package_assignment_service import (
    PatientPackageAssignmentService,
)
from lib.services.patient_plan_service import PatientPlanService
from lib.services.patient_profile_service import PatientProfileService
from lib.services.patient_profile_vector_service.patient_profile_vector_service import (
    PatientProfileVectorService,
)
from lib.services.patient_sleep_service import PatientSleepService
from lib.services.patient_smbg_service import PatientSmbgService
from lib.services.patient_vital_service import PatientVitalService
from lib.services.patient_summary import PatientSummaryService
from lib.services.active_patient_service import ActivePatientService
from lib.services.osteoflag_service import OsteoFlagService
from lib.services.prescription_analysis_service import (
    PrescriptionAnalysisService,
)
from lib.services.prescription_service import PrescriptionService
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
from lib.services.patient_query_service import PatientQueryService
from lib.services.patient_enrichment_service import PatientEnrichmentService
from lib.services.care_provider_query_service import CareProviderQueryService
from lib.services.package_query_service import PackageQueryService
from lib.utils.fitness.processor import FitnessStatsProcessor
from lib.utils.cgm.processor import CGMStatsProcessor
from lib.utils.meals.processor import MealStatsProcessor
from lib.utils.sleep.sleep_stats_processor import SleepStatsProcessor
from lib.utils.smbg.processor import SMBGStatsProcessor

# Weight Loss Agent Service
from lib.services.weight_loss_agent_service import WeightLossAgentService
from lib.services.weightloss_agent.analytics_service import AnalyticsService
from lib.services.weightloss_agent.intake_service import IntakeService
from lib.services.weightloss_agent.safety_rules_service import (
    SafetyRulesService,
)
from lib.services.weightloss_agent.plan_composer_service import (
    PlanComposerService,
)
from lib.services.weightloss_agent.coach_messenger_service import (
    CoachMessengerService,
)
from lib.services.weightloss_agent.glp1_symptoms_service import (
    Glp1SymptomsService,
)
from lib.services.weightloss_agent.agentic_orchestrator import (
    AgenticOrchestrator,
)

from lib.services.health_query_agent.service import HealthQueryAgentService


def get_libreview_sync_queue() -> SQSService:
    return cast(SQSService, container.resolve("libreview_sync_queue"))


def get_user_device_service() -> UserDeviceService:
    return cast(UserDeviceService, container.resolve(UserDeviceService))


def get_patient_query_service() -> PatientQueryService:
    return cast(PatientQueryService, container.resolve(PatientQueryService))


def get_patient_enrichment_service() -> PatientEnrichmentService:
    return cast(
        PatientEnrichmentService,
        container.resolve(PatientEnrichmentService),
    )


def get_care_provider_query_service() -> CareProviderQueryService:
    return cast(
        CareProviderQueryService,
        container.resolve(CareProviderQueryService),
    )


def get_package_query_service() -> PackageQueryService:
    return cast(
        PackageQueryService,
        container.resolve(PackageQueryService),
    )


def get_chat_messaging_service() -> ChatMessagingService:
    return cast(ChatMessagingService, container.resolve(ChatMessagingService))


def get_chat_notification_service() -> ChatNotificationService:
    return cast(
        ChatNotificationService, container.resolve(ChatNotificationService)
    )


def get_chat_management_service() -> ChatManagementService:
    return cast(
        ChatManagementService, container.resolve(ChatManagementService)
    )


def get_ai_conversation_service() -> AiConversationService:
    return cast(
        AiConversationService, container.resolve(AiConversationService)
    )


def get_ai_conversation_service_v2() -> AiConversationServiceV2:
    return cast(
        AiConversationServiceV2, container.resolve(AiConversationServiceV2)
    )


def get_patient_profile_service() -> PatientProfileService:
    return cast(
        PatientProfileService, container.resolve(PatientProfileService)
    )


def get_care_provider_profile_service() -> CareProviderProfileService:
    return cast(
        CareProviderProfileService,
        container.resolve(CareProviderProfileService),
    )


def get_health_facility_service() -> HealthFacilityService:
    return cast(
        HealthFacilityService,
        container.resolve(HealthFacilityService),
    )


def get_package_service() -> PackageService:
    return cast(
        PackageService,
        container.resolve(PackageService),
    )


def get_patient_connected_app_service() -> PatientConnectedAppService:
    return cast(
        PatientConnectedAppService,
        container.resolve(PatientConnectedAppService),
    )


def get_patient_smbg_service() -> PatientSmbgService:
    return cast(
        PatientSmbgService,
        container.resolve(PatientSmbgService),
    )


def get_patient_vital_service() -> PatientVitalService:
    return cast(
        PatientVitalService,
        container.resolve(PatientVitalService),
    )


def get_patient_summary_service() -> PatientSummaryService:
    return cast(
        PatientSummaryService,
        container.resolve(PatientSummaryService),
    )


def get_active_patient_service() -> ActivePatientService:
    return cast(
        ActivePatientService,
        container.resolve(ActivePatientService),
    )


def get_patient_sleep_service() -> PatientSleepService:
    return cast(
        PatientSleepService,
        container.resolve(PatientSleepService),
    )


def get_meal_analysis_service() -> MealAnalysisService:
    return cast(
        MealAnalysisService,
        container.resolve(MealAnalysisService),
    )


def get_meal_service() -> MealService:
    return cast(
        MealService,
        container.resolve(MealService),
    )


def get_prescription_service() -> PrescriptionService:
    return cast(PrescriptionService, container.resolve(PrescriptionService))


def get_weightloss_analytics_service() -> AnalyticsService:
    return cast(AnalyticsService, container.resolve(AnalyticsService))


def get_intake_service() -> IntakeService:
    return cast(IntakeService, container.resolve(IntakeService))


def get_safety_rules_service() -> SafetyRulesService:
    return cast(SafetyRulesService, container.resolve(SafetyRulesService))


def get_plan_composer_service() -> PlanComposerService:
    return cast(PlanComposerService, container.resolve(PlanComposerService))


def get_coach_messenger_service() -> CoachMessengerService:
    return cast(
        CoachMessengerService, container.resolve(CoachMessengerService)
    )


def get_glp1_symptoms_service() -> Glp1SymptomsService:
    return cast(Glp1SymptomsService, container.resolve(Glp1SymptomsService))


def get_agentic_orchestrator_service() -> AgenticOrchestrator:
    return cast(AgenticOrchestrator, container.resolve(AgenticOrchestrator))


def get_prescription_analysis_service() -> PrescriptionAnalysisService:
    return cast(
        PrescriptionAnalysisService,
        container.resolve(PrescriptionAnalysisService),
    )


def get_osteoflag_service() -> OsteoFlagService:
    return cast(OsteoFlagService, container.resolve(OsteoFlagService))


def get_patient_plan_service() -> PatientPlanService:
    return cast(
        PatientPlanService,
        container.resolve(PatientPlanService),
    )


def get_patient_package_assignment_service() -> (
    PatientPackageAssignmentService
):
    return cast(
        PatientPackageAssignmentService,
        container.resolve(PatientPackageAssignmentService),
    )


def get_patient_document_service() -> PatientDocumentService:
    return cast(
        PatientDocumentService, container.resolve(PatientDocumentService)
    )


def get_patient_document_research_service() -> PatientDocumentResearchService:
    return cast(
        PatientDocumentResearchService,
        container.resolve(PatientDocumentResearchService),
    )


def get_cgm_service() -> CGMUploadService:
    return cast(
        CGMUploadService,
        container.resolve(CGMUploadService),
    )


def get_cgm_report_service() -> CGMReportService:
    return cast(
        CGMReportService,
        container.resolve(CGMReportService),
    )


def get_fitness_stats_processor() -> FitnessStatsProcessor:
    return cast(
        FitnessStatsProcessor,
        container.resolve(FitnessStatsProcessor),
    )


def get_fitness_report_service() -> FitnessReportService:
    return cast(FitnessReportService, container.resolve(FitnessReportService))


def get_cgm_stats_processor() -> CGMStatsProcessor:
    return cast(CGMStatsProcessor, container.resolve(CGMStatsProcessor))


def get_sleep_stats_processor() -> SleepStatsProcessor:
    return cast(
        SleepStatsProcessor,
        container.resolve(SleepStatsProcessor),
    )


def get_sleep_report_service() -> SleepReportService:
    return cast(SleepReportService, container.resolve(SleepReportService))


def get_meal_stats_processor() -> MealStatsProcessor:
    return cast(MealStatsProcessor, container.resolve(MealStatsProcessor))


def get_meal_report_service() -> MealReportService:
    return cast(MealReportService, container.resolve(MealReportService))


def get_smbg_stats_processor() -> SMBGStatsProcessor:
    return cast(SMBGStatsProcessor, container.resolve(SMBGStatsProcessor))


def get_fitness_upload_service() -> FitnessUploadService:
    return cast(FitnessUploadService, container.resolve(FitnessUploadService))


def get_celery_task_manager() -> CeleryTaskManager:
    return cast(
        CeleryTaskManager,
        container.resolve(CeleryTaskManager),
    )


def get_token_usage_service() -> TokenUsageService:
    return cast(
        TokenUsageService,
        container.resolve(TokenUsageService),
    )


def get_libreview_service() -> LibreViewService:
    return cast(LibreViewService, container.resolve(LibreViewService))


def get_ai_conversation_service_v1() -> AIConversationServiceV1:
    return cast(
        AIConversationServiceV1, container.resolve(AIConversationServiceV1)
    )


def get_qdrant_search_engine() -> QdrantSearchEngine:
    return cast(QdrantSearchEngine, container.resolve(QdrantSearchEngine))


def get_cgm_vector_service() -> CGMVectorService:
    return cast(CGMVectorService, container.resolve(CGMVectorService))


def get_fitness_vector_service() -> FitnessVectorService:
    return cast(FitnessVectorService, container.resolve(FitnessVectorService))


def get_meal_vector_service() -> MealVectorService:
    return cast(MealVectorService, container.resolve(MealVectorService))


def get_smbg_vector_service() -> SMBGVectorService:
    return cast(SMBGVectorService, container.resolve(SMBGVectorService))


def get_patient_profile_vector_service() -> PatientProfileVectorService:
    return cast(
        PatientProfileVectorService,
        container.resolve(PatientProfileVectorService),
    )


def get_ai_conversation_messages_collection():
    return container.resolve("ai_conversation_messages_collection")


def get_cgm_report_collection():
    return container.resolve("cgm_report_collection")


def get_fitness_report_collection():
    return container.resolve("fitness_report_collection")


def get_meal_report_collection():
    return container.resolve("meal_report_collection")


def get_sleep_report_collection():
    return container.resolve("sleep_report_collection")


def get_patient_documents_collection():
    return container.resolve("patient_documents")


def get_inbody_reports_collection():
    return container.resolve("inbody_reports_collection")


def get_weight_loss_interactions_collection():
    return container.resolve("weight_loss_interactions_collection")


def get_weight_loss_progress_analyses_collection():
    return container.resolve("weight_loss_progress_analyses_collection")


def get_patient_metrics_service() -> PatientMetricsService:
    return cast(
        PatientMetricsService, container.resolve(PatientMetricsService)
    )


def get_meal_metrics_service() -> MealMetricsService:
    return cast(MealMetricsService, container.resolve(MealMetricsService))


def get_smbg_metrics_service() -> SMBGMetricsService:
    return cast(SMBGMetricsService, container.resolve(SMBGMetricsService))


def get_cgm_metrics_service() -> CGMMetricsService:
    return cast(CGMMetricsService, container.resolve(CGMMetricsService))


def get_fitness_metrics_service() -> FitnessMetricsService:
    return cast(
        FitnessMetricsService, container.resolve(FitnessMetricsService)
    )


def get_health_facility_metrics_service() -> HealthFacilityMetricsService:
    return cast(
        HealthFacilityMetricsService,
        container.resolve(HealthFacilityMetricsService),
    )


def get_package_metrics_service() -> PackageMetricsService:
    return cast(
        PackageMetricsService, container.resolve(PackageMetricsService)
    )


def get_weight_loss_agent_service() -> WeightLossAgentService:
    return cast(
        WeightLossAgentService, container.resolve(WeightLossAgentService)
    )


def get_file_content_extractor_service() -> FileContentExtractorService:
    return cast(
        FileContentExtractorService,
        container.resolve(FileContentExtractorService),
    )


def get_cgm_qdrant_sync_cache_store() -> CacheStore:
    return cast(CacheStore, container.resolve("cgm_qdrant_sync"))


def get_fitness_qdrant_sync_cache_store() -> CacheStore:
    return cast(CacheStore, container.resolve("fitness_qdrant_sync"))


def get_cgm_sync_cache_store() -> CacheStore:
    return cast(CacheStore, container.resolve("cgm_sync"))


def get_health_query_agent_service() -> HealthQueryAgentService:
    return cast(
        HealthQueryAgentService,
        container.resolve(HealthQueryAgentService),
    )
