from fastapi import APIRouter
from read import router as read_router
from upload import router as upload_router


router = APIRouter(prefix="/patient/vitals", tags=["Vitals"])

router.include_router(read_router)
router.include_router(upload_router)
