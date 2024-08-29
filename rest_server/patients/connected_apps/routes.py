from fastapi import APIRouter
from read import router as read_router
from libreview import router as libreview_router
from other_app import router as other_app_router

router = APIRouter(prefix="/patient/connected-apps", tags=["ConnectedApps"])

router.include_router(read_router)
router.include_router(libreview_router)
router.include_router(other_app_router)
