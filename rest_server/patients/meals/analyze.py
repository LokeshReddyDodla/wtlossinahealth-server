from typing import Optional

from fastapi import Depends, HTTPException, Request, status

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.service_dependencies import (
    get_meal_service,
    get_meal_stats_processor,
)
from lib.models.patient import Patient
from lib.schemas.patient_diet_plan import MealDistribution
from lib.schemas.patient_meal import PatientMeal as PatientMealSchema
from lib.services.meal_service import MealService
from lib.utils.http_exceptions import raise_http_exception
from lib.services.reports import MealStatsProcessor
from rest_server.patients.meals.api_schema import PatientMealAnalysis
from rest_server.response_models import SuccessResponse

from .router import router


@router.post(
    path="/analyze",
    response_model=SuccessResponse,
)
async def analyze_meal_api(
    request: Request,
    meal_id: str,
    re_analyze: Optional[bool] = False,
    update_fields: Optional[dict] = None,
    meal_service: MealService = Depends(get_meal_service),
    meal_stats_processor: MealStatsProcessor = Depends(
        get_meal_stats_processor
    ),
    current_patient: Patient = Depends(get_current_patient),
):
    """
    Analyze Meal API
    """
    try:
        analyzed_meal = await meal_service.analyze_or_reanalyze_meal(
            meal_id=meal_id,
            re_analyze=re_analyze,
            update_fields=update_fields,
            patient_id=str(current_patient.patient_id),
        )

        meal_data = PatientMealSchema.from_orm(analyzed_meal)

        diet_recommendations_data = (
            await meal_stats_processor.get_diet_recommendation(
                str(current_patient.patient_id), meal_data.uploaded_at
            )
        )

        meal_recommendation = (
            diet_recommendations_data.snack
            if meal_data.type == "snack"
            else diet_recommendations_data.major_meal
        )

        validated_recommendations = MealDistribution.model_validate(
            meal_recommendation
        )

        return SuccessResponse(
            message="Meal analyzed successfully.",
            data=PatientMealAnalysis(
                meal_data=meal_data,
                meal_recommendation=validated_recommendations,
            ),
        )
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Meal analysis failed. Please try again later.",
            detail=str(e),
        )
