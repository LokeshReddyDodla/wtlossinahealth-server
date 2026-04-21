"""GET /v1/meals/{patient_id} and /{patient_id}/{meal_id}."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
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
from lib.services.care_provider_access_service import CareProviderAccessService
from lib.services.meal.service import MealService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.schemas.patient_meal import PatientMeal as PatientMealSchema
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.get("/{patient_id}", response_model=SuccessResponse)
async def list_meals(
    patient_id: str,
    start_datetime: Optional[datetime] = None,
    end_datetime: Optional[datetime] = None,
    analyzed: Optional[str] = None,
    limit: Optional[int] = None,
    meal_service: MealService = Depends(get_meal_service),
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[
                ProfileTypeEnum.ADMIN,
                ProfileTypeEnum.CARE_PROVIDER,
                ProfileTypeEnum.PATIENT,
            ],
            care_provider_feature=CareProviderFeature.MEALS,
            care_provider_action=CareProviderPermissionAction.READ,
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
    try:
        meals = await meal_service.fetch_meals(
            patient_id=str(verified_pid),
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            analyzed=analyzed,
            limit=limit,
        )
        return SuccessResponse(
            message="Meals fetched",
            data=[PatientMealSchema.from_orm(m) for m in meals],
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to load meals",
            detail=str(exc),
        )


@router.get("/{patient_id}/{meal_id}", response_model=SuccessResponse)
async def get_meal(
    patient_id: str,
    meal_id: str,
    meal_service: MealService = Depends(get_meal_service),
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[
                ProfileTypeEnum.ADMIN,
                ProfileTypeEnum.CARE_PROVIDER,
                ProfileTypeEnum.PATIENT,
            ],
            care_provider_feature=CareProviderFeature.MEALS,
            care_provider_action=CareProviderPermissionAction.READ,
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
    try:
        meal = await meal_service.fetch_meal(meal_id=meal_id)
        return SuccessResponse(
            message="Meal fetched",
            data=PatientMealSchema.from_orm(meal),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to load meal",
            detail=str(exc),
        )
