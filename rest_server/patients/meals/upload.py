import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.database import get_postgres_session
from lib.models.patient import Patient
from lib.models.patient_meal import PatientMeal
from rest_server.patients.meals.api_schema import (PatientMealResponse,
                                                   PatientMealUploadRequest,
                                                   PatientMealUploadResponse)
from rest_server.response_models import ErrorResponse, SuccessResponse

from .router import router


@router.post(path="/upload", response_model=PatientMealUploadResponse)
async def meal_upload_api(
    request: Request,
    meal_data: PatientMealUploadRequest,
    session: AsyncSession = Depends(get_postgres_session),
    current_patient: Patient = Depends(get_current_patient),
):
    """
    Meal Upload API
    """
    try:
        context_id = uuid.uuid4().hex

        meal = PatientMeal(
            type=meal_data.type,
            time=meal_data.datetime.time(),
            date=meal_data.datetime.date(),
            source=meal_data.source,
            description=meal_data.description,
            context_id=context_id,
            image_url=meal_data.image_url,
            patient_id=current_patient.patient_id,
        )
        session.add(meal)
        await session.commit()
        await session.refresh(meal)

        meal = PatientMealResponse.from_orm(meal)

        return PatientMealUploadResponse(
            message="Meal Uploaded Successfully",
            data=meal,
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
