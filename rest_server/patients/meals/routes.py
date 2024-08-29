from fastapi import APIRouter
from analyze_meal import router as analyze_meal_router
from read import router as read_router
from delete import router as delete_router
from upload import router as upload_router

router = APIRouter(prefix="/patient/meals", tags=["Meals"])

router.include_router(analyze_meal_router)
router.include_router(read_router)
router.include_router(delete_router)
router.include_router(upload_router)
