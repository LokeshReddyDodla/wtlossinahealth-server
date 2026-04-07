from fastapi import APIRouter

router = APIRouter(prefix="/patient", tags=["Patient"])

from .care_providers.router import router as care_providers_router
from .cgm.router import router as cgm_router
from .connected_apps.router import router as connected_apps_router
from .fitness.router import router as fitness_router
from .meals.router import router as meals_router
from .overview.router import router as overview_router
from .packages.router import router as packages_router
from .permissions.router import router as permissions_router
from .profile.router import router as profile_router
from .sleep.router import router as sleep_router
from .smbgs.router import router as smbgs_router
from .token_usage.router import router as token_usage_router
from .vitals.router import router as vitals_router

router.include_router(care_providers_router)
router.include_router(cgm_router)
router.include_router(connected_apps_router)
router.include_router(fitness_router)
router.include_router(meals_router)
router.include_router(overview_router)
router.include_router(packages_router)
router.include_router(permissions_router)
router.include_router(profile_router)
router.include_router(sleep_router)
router.include_router(smbgs_router)
router.include_router(token_usage_router)
router.include_router(vitals_router)
