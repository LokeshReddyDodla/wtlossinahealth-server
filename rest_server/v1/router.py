from fastapi import APIRouter
from .auth.router import router as auth_router
from .packages.router import router as packages_router
from .care_providers.router import router as care_providers_router
from .patients.router import router as patients_router
from .health_facilities.router import router as health_facilities_router
from .token_usage.router import router as token_usage_router
from .reports.router import router as reports_router
from .health_query_agent.router import router as health_query_agent_router
from .research_agent.router import router as research_agent_router
from .cohort_agent.router import router as cohort_agent_router
from .uploads.router import router as uploads_router
from .diet_plans.router import router as diet_plans_router
from .fitness_plans.router import router as fitness_plans_router
from .patient_exports.router import router as patient_exports_router
from .gamification.router import router as gamification_router
from .voice_agent.router import router as voice_agent_router
from .prescriptions.router import router as prescriptions_router
from .consultations.router import router as consultations_router
from .medications.router import router as medications_router
from .exercises.router import router as exercises_router
from .meals.router import router as meals_router
from .support_tickets.router import router as support_tickets_router
from .chats.router import router as v1_chats_router
from .documents.router import router as documents_router
from .share.router import router as share_router
from .admin.support_tickets.router import (
    router as admin_support_tickets_router,
)
from .admin.notifications.router import router as admin_notifications_router
from .product_bot.router import router as product_bot_router
from .whatsapp.router import router as whatsapp_router


router = APIRouter(prefix="/v1", tags=["V1"])

router.include_router(auth_router)
router.include_router(packages_router)
router.include_router(care_providers_router)
router.include_router(patients_router)
router.include_router(health_facilities_router)
router.include_router(token_usage_router)
router.include_router(reports_router)
router.include_router(health_query_agent_router)
router.include_router(research_agent_router)
router.include_router(cohort_agent_router)
router.include_router(uploads_router)
router.include_router(diet_plans_router)
router.include_router(fitness_plans_router)
router.include_router(patient_exports_router)
router.include_router(gamification_router)
router.include_router(voice_agent_router)
router.include_router(prescriptions_router)
router.include_router(consultations_router)
router.include_router(medications_router)
router.include_router(exercises_router)
router.include_router(meals_router)
router.include_router(support_tickets_router)
router.include_router(v1_chats_router)
router.include_router(documents_router)
router.include_router(admin_support_tickets_router)
router.include_router(admin_notifications_router)
router.include_router(share_router)
router.include_router(product_bot_router)
router.include_router(whatsapp_router)
