from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.service_dependencies import (get_meal_service,
                                                   get_meal_stats_processor,
                                                   get_patient_profile_service)
from lib.models.patient import Patient
from lib.models.patient_meal import PatientMeal as PatientMealModel
from lib.schemas.patient_diet_plan import (MealDistribution, PatientDietPlan,
                                           PatientDietPlanBase)
from lib.schemas.patient_meal import PatientMeal as PatientMealSchema
from lib.services.meal_service import MealService
from lib.services.patient_profile_service import PatientProfileService
from lib.utils.meals.processor import MealStatsProcessor
from rest_server.patients.meals.api_schema import (PatientMealAnalysis,
                                                   PatientMealAnalysisResponse)
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
        analyzed_meal = await meal_service.analyze_meal(
            meal_id=meal_id,
            re_analyze=re_analyze,
            patient_id=str(current_patient.patient_id),
            update_fields=update_fields,
        )

        meal_data = PatientMealSchema.from_orm(analyzed_meal)

        diet_recommendations_data = (
            await meal_stats_processor.get_diet_recommendations(
                meal_data.uploaded_at
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

        return PatientMealAnalysisResponse(
            message="Meal analyzed successfully.",
            data=PatientMealAnalysis(
                meal_data=meal_data,
                meal_recommendation=validated_recommendations,
            ),
        )
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        response = ErrorResponse(
            message="Meal analysis failed. Please try again later.",
            detail=str(e),
        )
        raise HTTPException(status_code=500, detail=response.dict())
