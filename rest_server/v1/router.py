from fastapi import APIRouter
from .auth.router import router as auth_router
from .packages.router import router as packages_router
from .care_providers.router import router as care_providers_router
from .patients.router import router as patients_router
from .health_facilities.router import router as health_facilities_router
from .token_usage.router import router as token_usage_router
from .reports.router import router as reports_router
from .health_query_agent.router import router as health_query_agent_router
from .uploads.router import router as uploads_router
from .diet_plans.router import router as diet_plans_router
from .fitness_plans.router import router as fitness_plans_router
from .patient_exports.router import router as patient_exports_router
from .gamification.router import router as gamification_router


router = APIRouter(prefix="/v1", tags=["V1"])

router.include_router(auth_router)
router.include_router(packages_router)
router.include_router(care_providers_router)
router.include_router(patients_router)
router.include_router(health_facilities_router)
router.include_router(token_usage_router)
router.include_router(reports_router)
router.include_router(health_query_agent_router)
router.include_router(uploads_router)
router.include_router(diet_plans_router)
router.include_router(fitness_plans_router)
router.include_router(patient_exports_router)
router.include_router(gamification_router)
