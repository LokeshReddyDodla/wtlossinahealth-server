from fastapi import APIRouter


router = APIRouter(prefix="/ai", tags=["AI"])

from .care_provider.router import router as ai_care_providers_router
router.include_router(ai_care_providers_router)
