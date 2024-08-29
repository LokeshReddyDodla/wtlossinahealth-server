from fastapi import APIRouter
from read import router as read_router
from update import router as update_router

router = APIRouter(prefix="/patient/permissions", tags=["Permissions"])

router.include_router(read_router)
router.include_router(update_router)
