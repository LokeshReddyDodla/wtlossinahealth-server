from fastapi import APIRouter
from upload import router as upload_router
from read import router as read_router
from report import router as report_router

router = APIRouter(prefix="/patient/fitness", tags=["CGM"])

router.include_router(upload_router)
router.include_router(read_router)
router.include_router(report_router)
