import traceback
import uuid
from datetime import date, datetime, time, timezone
from typing import List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import asc, desc
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import Session, selectinload

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.database import get_postgres_session
from lib.dependencies.service_dependencies import (get_meal_service,
                                                   get_meal_stats_processor)
from lib.models.patient import Patient
from lib.models.patient_meal import PatientMeal as PatientMealModel
from lib.schemas.patient_meal import PatientMeal as PatientMealSchema
from lib.services.meal_service import MealService
from lib.utils.http_exceptions import raise_http_exception
from lib.utils.meals.processor import MealStatsProcessor
from rest_server.response_models import ErrorResponse, SuccessResponse

from .router import router


@router.get(
    path="",
    response_model=SuccessResponse,
)
async def get_meals_api(
    request: Request,
    from_datetime: Optional[datetime] = Query(None),
    to_datetime: Optional[datetime] = Query(None),
    source: Optional[str] = Query(None),
    analyzed: Optional[str] = Query(None, regex="^(true|false|both)$"),
    order_by: Optional[str] = Query("time"),
    order: Optional[str] = Query("desc"),
    limit: Optional[int] = Query(None),
    meal_service: MealService = Depends(get_meal_service),
    current_patient: Patient = Depends(get_current_patient),
):
    """
    Get Meals API
    """
    try:

        meals = await meal_service.fetch_meals(
            patient_id=str(current_patient.patient_id),
            from_datetime=from_datetime,
            to_datetime=to_datetime,
            source=source,
            analyzed=analyzed,
            order_by=order_by,
            order=order,
            limit=limit,
        )

        meals = [PatientMealSchema.from_orm(meal) for meal in meals]

        return SuccessResponse(
            message="Meals fetched successfully",
            data=meals,
        )
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )


@router.get(path="/stats/day", response_model=SuccessResponse)
async def get_meals_stats_api(
    request: Request,
    date: date,
    meal_stats_processor: MealStatsProcessor = Depends(
        get_meal_stats_processor
    ),
    current_patient: Patient = Depends(get_current_patient),
):
    """
    Get Meal Stats API
    """
    try:

        meal_stats = await meal_stats_processor.get_meal_stats_by_date(
            str(current_patient.patient_id), date
        )

        return SuccessResponse(
            message="Meal stats fetched successfully",
            data=meal_stats,
        )

    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
