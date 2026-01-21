from fastapi import APIRouter

router = APIRouter(prefix="/reports", tags=["V1 - Reports"])

from .cgm.router import router as cgm_router
from .smbg.router import router as smbg_router
from .meal.router import router as meal_router
from .fitness.router import router as fitness_router
from .sleep.router import router as sleep_router

router.include_router(cgm_router)
router.include_router(smbg_router)
router.include_router(meal_router)
router.include_router(fitness_router)
router.include_router(sleep_router)
