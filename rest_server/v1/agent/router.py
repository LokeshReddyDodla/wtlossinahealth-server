from fastapi import APIRouter

from .meal.router import router as meal_agent_router

router = APIRouter(prefix="/agent", tags=["V1 - Agent"])

router.include_router(meal_agent_router)
