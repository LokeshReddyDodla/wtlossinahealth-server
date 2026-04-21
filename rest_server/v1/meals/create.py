"""POST /v1/meals/{patient_id} — save a confirmed meal from preview."""

from __future__ import annotations

from uuid import UUID

from fastapi import Depends, status
from fastapi.exceptions import HTTPException

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.patient_access import resolve_patient_access
from lib.dependencies.service_dependencies import (
    get_care_provider_access_service,
    get_meal_service,
)
from lib.schemas.meal import MealCreateRequest
from lib.services.care_provider_access_service import CareProviderAccessService
from lib.services.meal.service import MealService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.post("/{patient_id}", response_model=SuccessResponse)
async def create_meal(
    patient_id: str,
    body: MealCreateRequest,
    meal_service: MealService = Depends(get_meal_service),
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[
                ProfileTypeEnum.ADMIN,
                ProfileTypeEnum.CARE_PROVIDER,
                ProfileTypeEnum.PATIENT,
            ],
            care_provider_feature=CareProviderFeature.MEALS,
            care_provider_action=CareProviderPermissionAction.CREATE,
        )
    ),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    verified_pid = await resolve_patient_access(
        actor=current_actor,
        patient_id=UUID(patient_id),
        care_provider_access_service=care_provider_access_service,
    )
    pid = str(verified_pid)

    try:
        meal = await meal_service.save_from_preview(patient_id=pid, request=body)
        return SuccessResponse(
            message="Meal saved",
            data={"meal_id": str(meal.id)},
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to save meal",
            detail=str(exc),
        )
