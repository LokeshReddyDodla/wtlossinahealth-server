from fastapi import APIRouter


from .health_facility.router import router as health_facilities_router
from .packages.router import router as packages_router

from .patients.cgm.router import router as patients_cgm_router
from .patients.fitness.router import router as patients_fitness_router
from .patients.meals.router import router as patients_meals_router
from .patients.smbg.router import router as patients_smbg_router
from .patients.prescriptions.router import (
    router as patients_prescriptions_router,
)
from .patients.profile.router import router as patients_profile_router
from .patients.documents.router import router as patients_document_router
from .patients.uploads.router import router as patients_uploads_router
from .patients.connected_apps.router import (
    router as patients_connected_apps_router,
)
from .patients.summaries.router import router as patients_summaries_router

from .profile.router import router as profile_router
from .dashboard_metrics.router import router as dashboard_metrics_router

router = APIRouter(prefix="/care-providers", tags=["Care Providers"])

router.include_router(profile_router)
router.include_router(health_facilities_router)
router.include_router(packages_router)


router.include_router(patients_profile_router)
router.include_router(patients_document_router)
router.include_router(patients_meals_router)
router.include_router(patients_smbg_router)
router.include_router(patients_fitness_router)
router.include_router(patients_cgm_router)
router.include_router(patients_uploads_router)
router.include_router(patients_prescriptions_router)
router.include_router(patients_connected_apps_router)
router.include_router(patients_summaries_router)

router.include_router(dashboard_metrics_router)

from .auth import *
