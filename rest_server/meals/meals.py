from typing import List, Optional
from datetime import datetime, timezone
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy import asc, desc
from sqlalchemy.future import select
from sqlalchemy.orm import Session

from lib.dependencies.auth import get_current_user
from lib.models.user import User
from lib.models.meal import FoodItem, Meal
from lib.schemas.meal import (
    MealResponse,
)
from rest_server.meals.api_schema import MealUploadRequest
from rest_server.response_models import ErrorResponse, SuccessResponse
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import SQLAlchemyError

# Create FastAPI router
router = APIRouter(prefix="/meal")


@router.get(path="/get", response_model=List[MealResponse], tags=["Meal"])
async def get_meals_api(
    request: Request,
    from_time: Optional[datetime] = Query(None),
    to_time: Optional[datetime] = Query(None),
    source: Optional[str] = Query(None),
    analyzed: Optional[str] = Query(None, regex="^(true|false|both)$"),
    order_by: Optional[str] = Query("time"),
    order: Optional[str] = Query("desc"),
    current_user: User = Depends(get_current_user),
    limit: Optional[int] = Query(None),
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
            if analyzed == "true":
                query = query.filter(Meal.analyzed == True)
            elif analyzed == "false":
                query = query.filter(Meal.analyzed == False)

            # Add ordering
            if order_by == "time":
                if order == "asc":
                    query = query.order_by(asc(Meal.time))
                else:
                    query = query.order_by(desc(Meal.time))
            elif order_by == "created_at":
                if order == "asc":
                    query = query.order_by(asc(Meal.uploaded_at))
                else:
                    query = query.order_by(desc(Meal.uploaded_at))

            # Apply limit if provided
            if limit is not None:
                query = query.limit(limit)

            result = await session.execute(query)
            meals = result.scalars().all()

            return meals
        except Exception as e:
            response = ErrorResponse(
                message="Internal Server Error", detail=str(e)
            )
            raise HTTPException(status_code=500, detail=response.dict())


@router.post(path="/upload", tags=["Meal"])
async def meal_upload_api(
    request: Request,
    meal_data: MealUploadRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Meal Upload API
    """
    async with request.state.context.postgres_store.get_session() as session:
        try:
            context_id = uuid.uuid4().hex

            meal = Meal(
                type=meal_data.type,
                time=meal_data.time,
                source=meal_data.source,
                description=meal_data.description,
                context_id=context_id,
                image_url=meal_data.image_url,
                user_id=current_user.user_id,
            )
            session.add(meal)
            await session.commit()
            await session.refresh(meal)

            return SuccessResponse(
                data=meal, message="Meal Uploaded Successfully"
            )
        except SQLAlchemyError as e:
            await session.rollback()
            response = ErrorResponse(message="Database Error", detail=str(e))
            raise HTTPException(status_code=500, detail=response.dict())
        except Exception as e:
            await session.rollback()
            response = ErrorResponse(
                message="Internal Server Error", detail=str(e)
            )
            raise HTTPException(status_code=500, detail=response.dict())
