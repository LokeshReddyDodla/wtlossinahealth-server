from typing import List, Optional, Union
from datetime import datetime, timezone
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy import asc, desc
from sqlalchemy.future import select
from sqlalchemy.orm import Session

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.models.patient import Patient

from lib.models.patient_meal import PatientFoodItem, PatientMeal

from rest_server.response_models import ErrorResponse, SuccessResponse
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import SQLAlchemyError
from .router import router


@router.delete(path="/{meal_id}", response_model=SuccessResponse)
async def delete_meal_api(
    request: Request,
    meal_id: uuid.UUID,
    current_patient: Patient = Depends(get_current_patient),
) -> Union[SuccessResponse, HTTPException]:
    """
    Delete Meal API
    """
    async with request.state.context.postgres_store.get_session() as session:
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
