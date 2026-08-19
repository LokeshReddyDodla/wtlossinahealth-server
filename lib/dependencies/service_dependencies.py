from typing import cast

from lib.core.cache_store import CacheStore
from lib.core.container import container
from lib.managers.arq_task_manager import ArqTaskManager, get_arq_task_manager
from lib.services.care_provider_access_service import (
    CareProviderAccessService,
)
from lib.services.daily_checkin_service import DailyCheckinService
from lib.services.notifications.service import PatientNotificationService
from lib.services.care_provider_profile_service import (
    CareProviderProfileService,
)
from lib.services.reports import CGMReportService

from lib.services.vector import CGMVectorService
from lib.services.cgm_upload_service import CGMUploadService
from lib.services.fcm_service import FCMService
from lib.services.chat.chat_management_service import ChatManagementService
from lib.services.chat.chat_messaging_service import ChatMessagingService
from lib.services.chat.chat_notification_service import ChatNotificationService
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
from lib.services.reports import FitnessReportService
from lib.services.fitness_upload_service import FitnessUploadService
from lib.services.vector import FitnessVectorService
from lib.services.health_facility_service import HealthFacilityService
from lib.services.libreview_service import LibreViewService
from lib.services.meal import MealService
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
from lib.services.vector import PatientProfileVectorService
from lib.services.patient_smbg_service import PatientSmbgService
from lib.services.patient_vital_service import PatientVitalService
from lib.services.patient_summary import PatientSummaryService
from lib.services.active_patient_service import ActivePatientService
from lib.services.osteoflag_service import OsteoFlagService
from lib.services.reports import SleepReportService
from lib.services.vector import SleepVectorService, SMBGVectorService, VitalsVectorService, WorkoutVectorService
from lib.services.sqs_service import SQSService
from lib.services.token_usage_service import TokenUsageService
from lib.services.user_device_service import UserDeviceService
from lib.services.patient_query_service import PatientQueryService
from lib.services.patient_enrichment_service import PatientEnrichmentService
from lib.services.care_provider_query_service import CareProviderQueryService
from lib.services.package_query_service import PackageQueryService
from lib.services.patient_data_availability_service import (
    PatientDataAvailabilityService,
)
from lib.services.patient_daily_overview_service import PatientDailyOverviewService
from lib.services.patient_timeline_service import PatientTimelineService
from lib.services.day_view.resolver import DayViewService
from lib.services.patient_data_export_service import PatientDataExportService

from lib.services.reports import (
    FitnessStatsProcessor,
    CGMStatsProcessor,
    MealStatsProcessor,
    SleepStatsProcessor,
    SMBGStatsProcessor,
)

from lib.services.profile_agent import ProfileAgentService

from lib.ai_foundation.agents.health_query import HealthQueryAgent
from lib.ai_foundation.agents.research_agent import ResearchAgent


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
    return cast(ChatNotificationService, container.resolve(ChatNotificationService))


def get_chat_management_service() -> ChatManagementService:
    return cast(ChatManagementService, container.resolve(ChatManagementService))


def get_support_ticket_service():
    from lib.services.support.support_ticket_service import SupportTicketService

    return cast(SupportTicketService, container.resolve(SupportTicketService))


def get_direct_chat_resolver() -> DirectChatResolver:
    return cast(DirectChatResolver, container.resolve(DirectChatResolver))


def get_patient_profile_service() -> PatientProfileService:
    return cast(PatientProfileService, container.resolve(PatientProfileService))


def get_patient_data_availability_service() -> PatientDataAvailabilityService:
    return cast(
        PatientDataAvailabilityService,
        container.resolve(PatientDataAvailabilityService),
    )


def get_patient_daily_overview_service() -> PatientDailyOverviewService:
    return cast(
        PatientDailyOverviewService, container.resolve(PatientDailyOverviewService)
    )


def get_patient_timeline_service() -> PatientTimelineService:
    return cast(PatientTimelineService, container.resolve(PatientTimelineService))


def get_day_view_service() -> DayViewService:
    return cast(DayViewService, container.resolve(DayViewService))


def get_progress_service():
    from lib.services.progress.resolver import ProgressService

    return cast(ProgressService, container.resolve(ProgressService))


def get_patient_brief_service():
    from lib.services.patient_brief.service import PatientBriefService

    return cast(PatientBriefService, container.resolve(PatientBriefService))


def get_patient_panel_service():
    from lib.services.patient_panel.service import PatientPanelService

    return cast(PatientPanelService, container.resolve(PatientPanelService))


def get_patient_data_export_service() -> PatientDataExportService:
    return cast(
        PatientDataExportService,
        container.resolve(PatientDataExportService),
    )


def get_care_provider_profile_service() -> CareProviderProfileService:
    return cast(
        CareProviderProfileService,
        container.resolve(CareProviderProfileService),
    )


def get_care_intent_service():
    from lib.services.care_intent_service import CareIntentService

    return cast(CareIntentService, container.resolve(CareIntentService))


def get_care_provider_access_service() -> CareProviderAccessService:
    return cast(
        CareProviderAccessService,
        container.resolve(CareProviderAccessService),
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


def get_daily_checkin_service() -> DailyCheckinService:
    return cast(
        DailyCheckinService,
        container.resolve(DailyCheckinService),
    )


def get_patient_notification_service() -> PatientNotificationService:
    return cast(
        PatientNotificationService,
        container.resolve(PatientNotificationService),
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


def get_meal_service() -> MealService:
    return cast(
        MealService,
        container.resolve(MealService),
    )


def get_meal_analysis_agent():
    from lib.ai_foundation.agents.meal_analysis.agent import MealAnalysisAgent

    return cast(MealAnalysisAgent, container.resolve(MealAnalysisAgent))


def get_speech_to_text():
    from lib.ai_foundation.voice.stt import BaseSpeechToText

    return cast(BaseSpeechToText, container.resolve(BaseSpeechToText))


def get_medication_service():
    from lib.services.medication_service import MedicationService  # avoid circular
    return cast(MedicationService, container.resolve(MedicationService))


def get_exercise_service():
    from lib.services.exercise_service import ExerciseService  # avoid circular
    return cast(ExerciseService, container.resolve(ExerciseService))


def get_patient_workout_service():
    from lib.services.patient_workout_service import PatientWorkoutService  # avoid circular
    return cast(PatientWorkoutService, container.resolve(PatientWorkoutService))


def get_workout_voice_service():
    from lib.services.workout_voice_service import WorkoutVoiceService  # avoid circular
    return cast(WorkoutVoiceService, container.resolve(WorkoutVoiceService))


def get_prescription_extraction_service():
    from lib.services.prescription_extraction_service import PrescriptionExtractionService  # avoid circular
    return cast(PrescriptionExtractionService, container.resolve(PrescriptionExtractionService))


def get_consultation_extraction_service():
    from lib.services.consultation_extraction_service import ConsultationExtractionService  # avoid circular
    return cast(ConsultationExtractionService, container.resolve(ConsultationExtractionService))


def get_consultation_service():
    from lib.services.consultation_service import ConsultationService  # avoid circular
    return cast(ConsultationService, container.resolve(ConsultationService))


def get_checkin_history_service():
    from lib.services.checkin_history_service import CheckinHistoryService  # avoid circular
    return cast(CheckinHistoryService, container.resolve(CheckinHistoryService))


def get_patient_facility_transfer_service():
    from lib.services.patient_facility_transfer_service import PatientFacilityTransferService
    return cast(PatientFacilityTransferService, container.resolve(PatientFacilityTransferService))



def get_inbody_report_service():
    from lib.services.inbody.service import InbodyReportService

    return cast(InbodyReportService, container.resolve(InbodyReportService))


def get_inbody_day_summary_service():
    from lib.services.inbody.day_summary_service import (
        InbodyDaySummaryService,
    )

    return cast(
        InbodyDaySummaryService,
        container.resolve(InbodyDaySummaryService),
    )


def get_inbody_trends_service():
    from lib.services.inbody.trends_service import InbodyTrendsService

    return cast(InbodyTrendsService, container.resolve(InbodyTrendsService))


def get_inbody_attribution_service():
    from lib.services.inbody.attribution_service import (
        InbodyAttributionService,
    )

    return cast(
        InbodyAttributionService,
        container.resolve(InbodyAttributionService),
    )


def get_inbody_vector_service():
    from lib.services.vector.inbody import InbodyVectorService

    return cast(InbodyVectorService, container.resolve(InbodyVectorService))


def get_osteoflag_service() -> OsteoFlagService:
    return cast(OsteoFlagService, container.resolve(OsteoFlagService))


def get_patient_diet_plan_service() -> PatientDietPlanService:
    return cast(
        PatientDietPlanService,
        container.resolve(PatientDietPlanService),
    )


def get_patient_fitness_plan_service() -> PatientFitnessPlanService:
    return cast(
        PatientFitnessPlanService,
        container.resolve(PatientFitnessPlanService),
    )


def get_patient_package_assignment_service() -> PatientPackageAssignmentService:
    return cast(
        PatientPackageAssignmentService,
        container.resolve(PatientPackageAssignmentService),
    )


def get_patient_document_service() -> PatientDocumentService:
    return cast(PatientDocumentService, container.resolve(PatientDocumentService))


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


def get_token_usage_service() -> TokenUsageService:
    return cast(
        TokenUsageService,
        container.resolve(TokenUsageService),
    )


def get_libreview_service() -> LibreViewService:
    return cast(LibreViewService, container.resolve(LibreViewService))


def get_cgm_vector_service() -> CGMVectorService:
    return cast(CGMVectorService, container.resolve(CGMVectorService))


def get_fitness_vector_service() -> FitnessVectorService:
    return cast(FitnessVectorService, container.resolve(FitnessVectorService))


def get_sleep_vector_service() -> SleepVectorService:
    return cast(SleepVectorService, container.resolve(SleepVectorService))


def get_meal_vector_service() -> MealVectorService:
    return cast(MealVectorService, container.resolve(MealVectorService))


def get_smbg_vector_service() -> SMBGVectorService:
    return cast(SMBGVectorService, container.resolve(SMBGVectorService))


def get_patient_profile_vector_service() -> PatientProfileVectorService:
    return cast(
        PatientProfileVectorService,
        container.resolve(PatientProfileVectorService),
    )


def get_vitals_vector_service() -> VitalsVectorService:
    return cast(VitalsVectorService, container.resolve(VitalsVectorService))


def get_workout_vector_service() -> WorkoutVectorService:
    return cast(WorkoutVectorService, container.resolve(WorkoutVectorService))


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





def get_patient_metrics_service() -> PatientMetricsService:
    return cast(PatientMetricsService, container.resolve(PatientMetricsService))


def get_meal_metrics_service() -> MealMetricsService:
    return cast(MealMetricsService, container.resolve(MealMetricsService))


def get_smbg_metrics_service() -> SMBGMetricsService:
    return cast(SMBGMetricsService, container.resolve(SMBGMetricsService))


def get_cgm_metrics_service() -> CGMMetricsService:
    return cast(CGMMetricsService, container.resolve(CGMMetricsService))


def get_fitness_metrics_service() -> FitnessMetricsService:
    return cast(FitnessMetricsService, container.resolve(FitnessMetricsService))


def get_health_facility_metrics_service() -> HealthFacilityMetricsService:
    return cast(
        HealthFacilityMetricsService,
        container.resolve(HealthFacilityMetricsService),
    )


def get_package_metrics_service() -> PackageMetricsService:
    return cast(PackageMetricsService, container.resolve(PackageMetricsService))




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


def get_health_query_agent() -> HealthQueryAgent:
    return cast(
        HealthQueryAgent,
        container.resolve(HealthQueryAgent),
    )


def get_research_agent() -> ResearchAgent:
    return cast(
        ResearchAgent,
        container.resolve(ResearchAgent),
    )


def get_profile_agent_service() -> ProfileAgentService:
    return cast(
        ProfileAgentService,
        container.resolve(ProfileAgentService),
    )


def get_fcm_service() -> FCMService:
    return FCMService()


def get_arq_task_manager_service() -> ArqTaskManager:
    return get_arq_task_manager()




# ── Gamification ─────────────────────────────────────────────────────────────

from lib.services.gamification.service import GamificationService
from lib.services.gamification.buddy_service import BuddyService
from lib.services.gamification.group_service import GroupService
from lib.services.gamification.challenge_service import ChallengeService
from lib.services.gamification.leaderboard_service import LeaderboardService
from lib.services.gamification.feed_service import FeedService
from lib.services.gamification.care_provider_service import CPGamificationService
from lib.services.gamification.event_handler import GamificationEventHandler
from lib.services.gamification.task_generator import TaskGeneratorService
from lib.services.gamification.streak_service import StreakService


def get_gamification_service() -> GamificationService:
    return cast(GamificationService, container.resolve(GamificationService))


def get_buddy_service() -> BuddyService:
    return cast(BuddyService, container.resolve(BuddyService))


def get_group_service() -> GroupService:
    return cast(GroupService, container.resolve(GroupService))


def get_challenge_service() -> ChallengeService:
    return cast(ChallengeService, container.resolve(ChallengeService))


def get_leaderboard_service() -> LeaderboardService:
    return cast(LeaderboardService, container.resolve(LeaderboardService))


def get_feed_service() -> FeedService:
    return cast(FeedService, container.resolve(FeedService))


def get_cp_gamification_service() -> CPGamificationService:
    return cast(CPGamificationService, container.resolve(CPGamificationService))


def get_gamification_event_handler() -> GamificationEventHandler:
    return cast(GamificationEventHandler, container.resolve(GamificationEventHandler))


def get_task_generator_service() -> TaskGeneratorService:
    return cast(TaskGeneratorService, container.resolve(TaskGeneratorService))


def get_streak_service() -> StreakService:
    return cast(StreakService, container.resolve(StreakService))


def get_product_bot_agent():
    from lib.ai_foundation.agents.product_bot import ProductBotAgent

    return cast(ProductBotAgent, container.resolve(ProductBotAgent))


# ── ai_foundation infrastructure providers ──────────────────────────────────
# One DI style for the API layer: route handlers take these via Depends()
# instead of calling container.resolve() in the function body.


def get_memory_store():
    from lib.ai_foundation.memory.mongo_store import MongoMemoryStore

    return cast(MongoMemoryStore, container.resolve(MongoMemoryStore))


def get_model_gateway():
    from lib.ai_foundation.models.gateway import ModelGateway

    return cast(ModelGateway, container.resolve(ModelGateway))


def get_model_registry():
    from lib.ai_foundation.models.registry import ModelRegistry

    return cast(ModelRegistry, container.resolve(ModelRegistry))


def get_insight_tracker():
    from lib.ai_foundation.agents.proactive_monitor.insight_tracker import InsightTracker

    return cast(InsightTracker, container.resolve(InsightTracker))


def get_patient_name_resolver():
    from lib.ai_foundation.agents.core.patient_resolver import PatientNameResolver

    return cast(PatientNameResolver, container.resolve(PatientNameResolver))


def get_proactive_monitor_agent():
    from lib.ai_foundation.agents.proactive_monitor import ProactiveMonitorAgent

    return cast(ProactiveMonitorAgent, container.resolve(ProactiveMonitorAgent))
