"""POST /v1/meals/{patient_id}/quick-preview — nutrition extraction only."""

from __future__ import annotations

from uuid import UUID

from fastapi import Depends, status
from fastapi.exceptions import HTTPException

from lib.ai_foundation.agents.meal_analysis.agent import MealAnalysisAgent
from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.patient_access import resolve_patient_access
from lib.dependencies.service_dependencies import (
    get_care_provider_access_service,
    get_meal_analysis_agent,
)
from lib.schemas.meal import MealPreviewRequest
from lib.services.care_provider_access_service import CareProviderAccessService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.post(
    "/{patient_id}/quick-preview",
    response_model=SuccessResponse,
)
async def quick_preview_meal(
    patient_id: str,
    body: MealPreviewRequest,
    agent: MealAnalysisAgent = Depends(get_meal_analysis_agent),
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
    """Extract food items and nutritional values only. No scoring or insights."""
    verified_pid = await resolve_patient_access(
        actor=current_actor,
        patient_id=UUID(patient_id),
        care_provider_access_service=care_provider_access_service,
    )
    pid = str(verified_pid)

    if not (body.image_url or body.text or body.items or body.repeat_of_meal_id):
        raise_http_exception(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="At least one of image_url, text, items, or repeat_of_meal_id is required.",
        )

    try:
        result = await agent.quick_analyze(patient_id=pid, request=body)
        return SuccessResponse(
            message="Meal extracted",
            data=result.model_dump(mode="json"),
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise_http_exception(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=str(exc),
        )
    except Exception as exc:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to extract meal nutrition. Please try again.",
            detail=str(exc),
        )
