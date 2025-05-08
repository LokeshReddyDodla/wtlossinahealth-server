from fastapi import APIRouter

router = APIRouter(prefix="/care-providers", tags=["Care Providers"])

from .health_facility.router import router as health_facility_router
from .packages.router import router as packages_router
from .patients.cgm.router import router as patients_cgm_router
from .patients.fitness.router import router as patients_fitness_router
from .patients.meals.router import router as patients_meals_router
from .patients.profile.router import router as patients_router
from .patients.report.router import router as patients_report_router
from .patients.uploads.router import router as patients_uploads_router
from .profile.router import router as profile_router

router.include_router(profile_router)
router.include_router(health_facility_router)
router.include_router(packages_router)
router.include_router(patients_router)
router.include_router(patients_report_router)
router.include_router(patients_meals_router)
router.include_router(patients_fitness_router)
router.include_router(patients_cgm_router)
router.include_router(patients_uploads_router)


from .auth import *
