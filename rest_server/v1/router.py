from fastapi import APIRouter

router = APIRouter(prefix="/v1", tags=["V1"])

from .packages.router import router as packages_router

router.include_router(packages_router)

