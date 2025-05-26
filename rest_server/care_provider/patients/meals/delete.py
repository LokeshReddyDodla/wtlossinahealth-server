from datetime import date
import uuid

from fastapi import Depends, HTTPException, Query, Request, status

from lib.dependencies.auth.care_provider_auth import get_current_care_provider
from lib.dependencies.service_dependencies import (
    get_meal_report_service,
    get_meal_service,
)
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.services.meal_report_service import MealReportService
from lib.services.meal_service import MealService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.delete(path="", response_model=SuccessResponse)
async def delete_meal_api(
    request: Request,
    patient_id: str = Query(...),
    meal_id: uuid.UUID = Query(...),
    meal_service: MealService = Depends(get_meal_service),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.DELETE, CareProviderFeature.MEALS
        )
    ),
):
    try:
        await meal_service.delete_meal(meal_id=meal_id, patient_id=patient_id)

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
