from fastapi import APIRouter

router = APIRouter(prefix="/admin", tags=["Admin"])

# from .care_provider.router import router as care_providers_router
# from .health_facility.router import router as health_facility_router
# from .connected_apps.router import router as connected_apps_router
