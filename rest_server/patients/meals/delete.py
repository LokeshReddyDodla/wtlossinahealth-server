import uuid

from fastapi import Depends, HTTPException, Query, Request, status

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.service_dependencies import get_meal_service
from lib.models.patient import Patient
from lib.services.meal_service import MealService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.delete(path="", response_model=SuccessResponse)
async def delete_meal_api(
    request: Request,
    meal_id: uuid.UUID = Query(...),
    meal_service: MealService = Depends(get_meal_service),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        await meal_service.delete_meal(
            meal_id=meal_id, patient_id=str(current_patient.patient_id)
        )

        return SuccessResponse(
            message="Meal deleted successfully. Your reports will be updated shortly."
        )
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
