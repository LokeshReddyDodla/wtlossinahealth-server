"""Meal preview endpoints — full analysis, quick (nutrition-only), and insights."""

from __future__ import annotations

from uuid import UUID

from fastapi import Depends, status
from fastapi.exceptions import HTTPException

from lib.ai_foundation.agents.meal_analysis.agent import MealAnalysisAgent
from lib.core.constants import AIFeatureEnum, ProfileTypeEnum
from lib.services.ai_feature_toggle_service import ai_feature_toggle_service
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.patient_access import resolve_patient_access
from lib.dependencies.service_dependencies import (
    get_care_provider_access_service,
    get_meal_analysis_agent,
)
from lib.schemas.meal import MealInsightsRequest, MealPreviewRequest
from lib.services.care_provider_access_service import CareProviderAccessService
from lib.services.meal.box_cache import cache_extraction_boxes
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router

_PREVIEW_DEPS = dict(
    allowed_roles=[
        ProfileTypeEnum.ADMIN,
        ProfileTypeEnum.CARE_PROVIDER,
        ProfileTypeEnum.PATIENT,
    ],
    care_provider_feature=CareProviderFeature.MEALS,
    care_provider_action=CareProviderPermissionAction.READ,
)


def _validate_input(body: MealPreviewRequest) -> None:
    if not (body.image_url or body.image_urls or body.text or body.items or body.repeat_of_meal_id):
        raise_http_exception(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="At least one of image_url(s), text, items, or repeat_of_meal_id is required.",
        )


@router.post(
    "/{patient_id}/preview",
    response_model=SuccessResponse,
)
async def preview_meal(
    patient_id: str,
    body: MealPreviewRequest,
    agent: MealAnalysisAgent = Depends(get_meal_analysis_agent),
    current_actor: Actor = Depends(get_current_actor(**_PREVIEW_DEPS)),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    """Analyze a meal (image/text/items) and return suggestions. No DB write."""
    verified_pid = await resolve_patient_access(
        actor=current_actor,
        patient_id=UUID(patient_id),
        care_provider_access_service=care_provider_access_service,
    )
    pid = str(verified_pid)
    await ai_feature_toggle_service.require_for_patients(
        AIFeatureEnum.MEAL_ANALYSIS, [pid]
    )
    _validate_input(body)

    try:
        result = await agent.analyze(patient_id=pid, request=body)
        await cache_extraction_boxes(result.model_trace_id, result.extraction.items)
        return SuccessResponse(
            message="Meal analyzed",
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
            message="Failed to analyze the meal. Please try again.",
            detail=str(exc),
        )


@router.post(
    "/{patient_id}/quick-preview",
    response_model=SuccessResponse,
)
async def quick_preview_meal(
    patient_id: str,
    body: MealPreviewRequest,
    agent: MealAnalysisAgent = Depends(get_meal_analysis_agent),
    current_actor: Actor = Depends(get_current_actor(**_PREVIEW_DEPS)),
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
    await ai_feature_toggle_service.require_for_patients(
        AIFeatureEnum.MEAL_ANALYSIS, [pid]
    )
    _validate_input(body)

    try:
        result = await agent.quick_analyze(patient_id=pid, request=body)
        await cache_extraction_boxes(result.model_trace_id, result.extraction.items)
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


@router.post(
    "/{patient_id}/insights",
    response_model=SuccessResponse,
)
async def meal_insights(
    patient_id: str,
    body: MealInsightsRequest,
    agent: MealAnalysisAgent = Depends(get_meal_analysis_agent),
    current_actor: Actor = Depends(get_current_actor(**_PREVIEW_DEPS)),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    """Run scoring/alternatives/glucose/plan/repeat on an existing extraction."""
    verified_pid = await resolve_patient_access(
        actor=current_actor,
        patient_id=UUID(patient_id),
        care_provider_access_service=care_provider_access_service,
    )
    pid = str(verified_pid)
    await ai_feature_toggle_service.require_for_patients(
        AIFeatureEnum.MEAL_ANALYSIS, [pid]
    )

    try:
        result = await agent.insights(patient_id=pid, request=body)
        return SuccessResponse(
            message="Meal insights generated",
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
            message="Failed to generate meal insights. Please try again.",
            detail=str(exc),
        )
