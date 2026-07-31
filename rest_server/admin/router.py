from fastapi import APIRouter

router = APIRouter(prefix="/admin", tags=["Admin"])


from .patients.uploads.router import router as patients_uploads_router
from .patients.connected_apps.router import router as patients_connected_apps_router

from .health_facility.router import router as health_facility_router

from .care_providers.profile.router import router as care_providers_profile_router

from .reports.router import router as reports_router

from .ai_features.router import router as ai_features_router

router.include_router(patients_uploads_router)
router.include_router(patients_connected_apps_router)

router.include_router(health_facility_router)

router.include_router(care_providers_profile_router)

router.include_router(reports_router)

router.include_router(ai_features_router)


from .auth import *