from fastapi import APIRouter
from upload import router as upload_router
from delete import router as delete_router

router = APIRouter(prefix="/patient/cgm", tags=["CGM"])

router.include_router(upload_router)
router.include_router(delete_router)
