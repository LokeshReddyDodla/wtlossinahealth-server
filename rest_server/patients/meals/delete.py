import uuid

from fastapi import Depends, HTTPException, Request, status

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.service_dependencies import get_meal_service
from lib.models.patient import Patient
from lib.services.meal_service import MealService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.delete(path="/clear_meals", response_model=SuccessResponse)
async def clear_all_meals_api(
    request: Request,
    meal_service: MealService = Depends(get_meal_service),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        await meal_service.delete_all_meals_for_patient(
            patient_id=str(current_patient.patient_id)
        )

        return SuccessResponse(message="All meals deleted successfully.")
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )


@router.delete(path="/{meal_id}", response_model=SuccessResponse)
async def delete_meal_api(
    request: Request,
    meal_id: uuid.UUID,
    meal_service: MealService = Depends(get_meal_service),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        await meal_service.delete_meal(meal_id=meal_id)

        return SuccessResponse(message="Meal deleted successfully.")
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
