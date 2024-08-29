from fastapi import APIRouter
from health_check import router

router = APIRouter(prefix="/health", tags=["Health"])

router.include_router(router)
