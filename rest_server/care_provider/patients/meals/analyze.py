from typing import Optional

from fastapi import Depends, HTTPException, Request, status

from lib.dependencies.auth.care_provider_auth import get_current_care_provider
from lib.dependencies.service_dependencies import (
    get_meal_service,
    get_meal_stats_processor,
)
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.schemas.patient_diet_plan import DietRecommendation
from lib.schemas.patient_meal import PatientMeal as PatientMealSchema
from lib.services.meal import MealService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from lib.services.reports import MealStatsProcessor
from rest_server.patients.meals.api_schema import PatientMealAnalysis
from rest_server.response_models import SuccessResponse

from .router import router


@router.post(
    path="/{meal_id}/analyze",
    response_model=SuccessResponse,
)
async def analyze_meal(
    request: Request,
    meal_id: str,
    patient_id: str,
    re_analyze: Optional[bool] = False,
    update_fields: Optional[dict] = None,
    meal_service: MealService = Depends(get_meal_service),
    meal_stats_processor: MealStatsProcessor = Depends(get_meal_stats_processor),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.CREATE, CareProviderFeature.REPORTS
        )
    ),
):
    try:
        analyzed_meal = await meal_service.analyze_or_reanalyze_meal(
            meal_id=meal_id,
            re_analyze=re_analyze,
            update_fields=update_fields,
            patient_id=str(patient_id),
        )  # type: ignore

        meal_data = PatientMealSchema.from_orm(analyzed_meal)

        diet_recommendations_data = await meal_stats_processor.get_diet_recommendation(
            str(patient_id), meal_data.uploaded_at
        )

        validated_recommendations = DietRecommendation.model_validate(
            diet_recommendations_data
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
