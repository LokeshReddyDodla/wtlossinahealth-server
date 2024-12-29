from fastapi import APIRouter

router = APIRouter(prefix="/care-providers", tags=["Care Providers"])

from .health_facility.router import router as health_facility_router
from .packages.router import router as packages_router
from .patients.profile.router import router as patients_router
from .patients.report.router import router as patients_report_router
from .profile.router import router as profile_router

router.include_router(profile_router)
router.include_router(health_facility_router)
router.include_router(packages_router)
router.include_router(patients_router)
router.include_router(patients_report_router)

from .auth import *
