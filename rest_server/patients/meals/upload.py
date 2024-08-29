import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Query

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.models.patient import Patient

from lib.models.patient_meal import PatientMeal
from rest_server.patients.meals.api_schema import (
    PatientMealResponse,
    PatientMealUploadRequest,
)
from rest_server.response_models import ErrorResponse, SuccessResponse
from sqlalchemy.exc import SQLAlchemyError
from .router import router


@router.post(path="/upload", tags=["Meals"])
async def meal_upload_api(
    request: Request,
    meal_data: PatientMealUploadRequest,
    current_patient: Patient = Depends(get_current_patient),
):
    """
    Meal Upload API
    """
    async with request.state.context.postgres_store.get_session() as session:
        try:
            context_id = uuid.uuid4().hex

            meal = PatientMeal(
                type=meal_data.type,
                time=meal_data.time,
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
