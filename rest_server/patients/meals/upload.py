import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.database import get_postgres_session
from lib.dependencies.service_dependencies import get_meal_service
from lib.models.patient import Patient
from lib.models.patient_meal import PatientMeal as PatientMealModel
from lib.schemas.patient_meal import PatientMeal as PatientMealSchema
from lib.services.meal_service import MealService
from rest_server.patients.meals.api_schema import (PatientMealUploadRequest,
                                                   PatientMealUploadResponse)
from rest_server.response_models import ErrorResponse, SuccessResponse

from .router import router


@router.post(path="/upload", response_model=PatientMealUploadResponse)
async def meal_upload_api(
    request: Request,
    meal_data: PatientMealUploadRequest,
    meal_service: MealService = Depends(get_meal_service),
    current_patient: Patient = Depends(get_current_patient),
):
    """
    Meal Upload API
    """
    try:
        new_meal = await meal_service.upload_meal(
            meal_data=meal_data, patient_id=str(current_patient.patient_id)
        )

        meal = PatientMealSchema.from_orm(new_meal)

        return PatientMealUploadResponse(
            message="Meal Uploaded Successfully",
            data=meal,
        )
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        response = ErrorResponse(
            message="Internal Server Error", detail=str(e)
        )
        raise HTTPException(status_code=500, detail=response.dict())
