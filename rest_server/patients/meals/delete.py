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
from lib.models.patient import Patient
from lib.models.patient_meal import PatientFoodItem, PatientMeal
from rest_server.response_models import ErrorResponse, SuccessResponse

from .router import router


@router.delete(path="/clear_meals", response_model=SuccessResponse)
async def clear_all_meals_api(
    request: Request,
    session: AsyncSession = Depends(get_postgres_session),
    current_patient: Patient = Depends(get_current_patient),
):
    """
    Clear All Meals API
    """
    try:
        # Delete all meals for the current patient
        delete_query = delete(PatientMeal).where(
            PatientMeal.patient_id == current_patient.patient_id
        )

        result = await session.execute(delete_query)
        await session.commit()

        # Check if any rows were deleted
        if result.rowcount == 0:
            raise HTTPException(
                status_code=404, detail="No meals found to delete."
            )

        return SuccessResponse(message="All meals deleted successfully.")
    except HTTPException as http_exc:
        raise http_exc
    except SQLAlchemyError as e:
        await session.rollback()
        response = ErrorResponse(
            message="Internal Server Error", detail=str(e)
        )
        raise HTTPException(status_code=500, detail=response.dict())


@router.delete(path="/{meal_id}", response_model=SuccessResponse)
async def delete_meal_api(
    request: Request,
    meal_id: uuid.UUID,
    session: AsyncSession = Depends(get_postgres_session),
    current_patient: Patient = Depends(get_current_patient),
):
    """
    Delete Meal API
    """
    try:
        meal = await session.get(PatientMeal, meal_id)
        if not meal:
            raise HTTPException(status_code=404, detail="Meal not found")

        if meal.patient_id != current_patient.patient_id:
            raise HTTPException(
                status_code=403,
                detail="Not authorized to delete this meal",
            )

        await session.delete(meal)
        await session.commit()

        return SuccessResponse(message="Meal deleted successfully.")
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        await session.rollback()
        response = ErrorResponse(
            message="Internal Server Error", detail=str(e)
        )
        raise HTTPException(status_code=500, detail=response.dict())
