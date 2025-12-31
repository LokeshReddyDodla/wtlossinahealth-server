from fastapi import APIRouter

router = APIRouter(prefix="/v1", tags=["V1"])

from .packages.router import router as packages_router
from .care_providers.router import router as care_providers_router
from .patients.router import router as patients_router
from .health_facilities.router import router as health_facilities_router

router.include_router(packages_router)
router.include_router(care_providers_router)
router.include_router(patients_router)
router.include_router(health_facilities_router)

