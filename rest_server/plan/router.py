"""Plan composer endpoints for generating and retrieving snapshots."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from lib.dependencies.service_dependencies import get_plan_composer_service
from lib.schemas.weightloss_agent.plan import (
    PlanGenerateRequest,
    PlanGenerateResponse,
    PlanDetailResponse,
)
from lib.services.weightloss_agent.plan_composer_service import (
    PlanComposerService,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

router = APIRouter(prefix="/plan", tags=["Plan"])


@router.post(
    "/generate",
    response_model=SuccessResponse[PlanGenerateResponse],
    status_code=status.HTTP_200_OK,
)
async def generate_plan(
    payload: PlanGenerateRequest,
    plan_service: PlanComposerService = Depends(get_plan_composer_service),
) -> SuccessResponse[PlanGenerateResponse]:
    response = await plan_service.generate_plan(payload)
    return SuccessResponse(
        message="Plan generation complete",
        data=response,
    )


@router.get(
    "/current",
    response_model=SuccessResponse[PlanDetailResponse],
    status_code=status.HTTP_200_OK,
)
async def get_current_plan(
    user_id: UUID = Query(..., description="Patient identifier"),
    plan_service: PlanComposerService = Depends(get_plan_composer_service),
) -> SuccessResponse[PlanDetailResponse]:
    plan_details = await plan_service.get_current_plan_details(user_id)
    if not plan_details:
        raise_http_exception(
            status.HTTP_404_NOT_FOUND, message="Plan not found for user"
        )
    plan_snapshot = plan_details["plan_snapshot"]
    ai_recommendations = plan_details.get("ai_recommendations")
    payload = plan_snapshot.model_dump()
    payload.pop("provenance", None)
    payload["ai_recommendations"] = ai_recommendations
    data = PlanDetailResponse(**payload)
    return SuccessResponse(
        message="Full plan retrieved successfully",
        provenance=plan_snapshot.provenance,
        data=data,
    )
