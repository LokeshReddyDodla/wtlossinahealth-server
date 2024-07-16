from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy.future import select
from sqlalchemy.orm import Session

from lib.dependencies.auth import get_current_user
from lib.models.user import User
from lib.models.meal import FoodItem, Meal
from lib.schemas.meal import (
    MealResponse,
    NutritionalValues,
    TotalNutritionalValue,
)
from rest_server.response_models import ErrorResponse
from sqlalchemy.orm import selectinload

# Create FastAPI router
router = APIRouter(prefix="/meal")


@router.get(path="/get", response_model=List[MealResponse], tags=["Meal"])
async def get_meals_api(
    request: Request,
    from_time: Optional[datetime] = Query(None),
    to_time: Optional[datetime] = Query(None),
    source: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
):
    """
    Get Meals API
    """
    async with request.state.context.postgres_store.get_session() as session:
        try:
            query = (
                select(Meal)
                .where(Meal.user_id == current_user.user_id)
                .options(
                    selectinload(Meal.items).selectinload(
                        FoodItem.nutritional_values
                    ),
                    selectinload(Meal.total_nutritional_value),
                )
            )

            if from_time:
                query = query.filter(Meal.time >= from_time)
            if to_time:
                query = query.filter(Meal.time <= to_time)
            if source:
                query = query.filter(Meal.source == source)

            result = await session.execute(query)
            meals = result.scalars().all()

            return meals
        except Exception as e:
            response = ErrorResponse(
                message="Internal Server Error", detail=str(e)
            )
            raise HTTPException(status_code=500, detail=response.dict())
