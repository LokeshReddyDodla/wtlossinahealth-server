
from fastapi import Depends, HTTPException, Request, status

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.service_dependencies import get_meal_service
from lib.models.patient import Patient
from lib.schemas.patient_meal import PatientMeal as PatientMealSchema
from lib.services.meal_service import MealService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.patients.meals.api_schema import PatientMealUploadRequest
from rest_server.response_models import SuccessResponse

from .router import router


@router.post(path="/upload", response_model=SuccessResponse)
async def meal_upload_api(
    request: Request,
    meal_data: PatientMealUploadRequest,
    meal_service: MealService = Depends(get_meal_service),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        new_meal = await meal_service.upload_meal(
            meal_data=meal_data, patient_id=str(current_patient.patient_id)
        )

        return SuccessResponse(
            message="Meal Uploaded Successfully",
            data=PatientMealSchema.from_orm(new_meal),
        )
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
