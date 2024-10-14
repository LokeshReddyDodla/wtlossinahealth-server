from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.service_dependencies import (get_meal_service,
                                                   get_patient_profile_service)
from lib.models.patient import Patient
from lib.services.meal_service import MealService
from lib.services.patient_profile_service import PatientProfileService
from rest_server.patients.meals.api_schema import (PatientMealAnalysisResponse,
                                                   PatientMealResponse)
from rest_server.response_models import ErrorResponse

from .router import router


@router.post(
    path="/analyze",
    response_model=PatientMealAnalysisResponse,
)
async def analyze_meal_api(
    request: Request,
    meal_id: str,
    re_analyze: Optional[bool] = False,
    meal_service: MealService = Depends(get_meal_service),
    current_patient: Patient = Depends(get_current_patient),
):
    """
    Analyze Meal API
    """
    try:
        meal = await meal_service.analyze_meal(
            meal_id=meal_id,
            re_analyze=re_analyze,
            patient_id=str(current_patient.patient_id),
        )

        meal_response = PatientMealResponse.from_orm(meal)

        return PatientMealAnalysisResponse(
            message="Meal analyzed successfully.",
            data=meal_response,
        )
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        response = ErrorResponse(
            message="Internal Server Error", detail=str(e)
        )
        raise HTTPException(status_code=500, detail=response.dict())
