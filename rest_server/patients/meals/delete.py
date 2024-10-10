import uuid
from datetime import datetime, timezone
from typing import List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import asc, delete, desc
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import Session, selectinload

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.database import get_postgres_session
from lib.dependencies.service_dependencies import get_meal_service
from lib.models.patient import Patient
from lib.models.patient_meal import PatientFoodItem, PatientMeal
from lib.services.meal_service import MealService
from rest_server.response_models import ErrorResponse, SuccessResponse

from .router import router


@router.delete(path="/clear_meals", response_model=SuccessResponse)
async def clear_all_meals_api(
    request: Request,
    meal_service: MealService = Depends(get_meal_service),
    current_patient: Patient = Depends(get_current_patient),
):
    """
    Clear All Meals API
    """
    try:
        await meal_service.delete_all_meals_for_patient(
            patient_id=str(current_patient.patient_id)
        )

        return SuccessResponse(message="All meals deleted successfully.")
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        response = ErrorResponse(
            message="Internal Server Error", detail=str(e)
        )
        raise HTTPException(status_code=500, detail=response.dict())


@router.delete(path="/{meal_id}", response_model=SuccessResponse)
async def delete_meal_api(
    request: Request,
    meal_id: uuid.UUID,
    meal_service: MealService = Depends(get_meal_service),
    current_patient: Patient = Depends(get_current_patient),
):
    """
    Delete Meal API
    """
    try:
        await meal_service.delete_meal(meal_id=meal_id)

        return SuccessResponse(message="Meal deleted successfully.")
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        response = ErrorResponse(
            message="Internal Server Error", detail=str(e)
        )
        raise HTTPException(status_code=500, detail=response.dict())
