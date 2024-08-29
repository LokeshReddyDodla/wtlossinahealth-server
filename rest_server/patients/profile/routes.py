from fastapi import APIRouter
from read import router as read_router
from create import router as create_router
from update import router as update_router
from delete import router as update_router


router = APIRouter(prefix="/patient/profile", tags=["Profile"])

router.include_router(read_router)
router.include_router(create_router)
router.include_router(update_router)
router.include_router(update_router)
