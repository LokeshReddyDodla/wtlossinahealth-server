"""Plan composer endpoints for generating and retrieving snapshots."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.patient_access import resolve_patient_access
from lib.dependencies.service_dependencies import (
    get_care_provider_access_service,
    get_plan_composer_service,
)
from lib.schemas.weightloss_agent.plan import (
    PlanGenerateRequest,
    PlanGenerateResponse,
    PlanDetailResponse,
)
from lib.services.care_provider_access_service import CareProviderAccessService
from lib.services.weightloss_agent.plan_composer_service import (
    PlanComposerService,
)
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
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
    actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[ProfileTypeEnum.PATIENT, ProfileTypeEnum.CARE_PROVIDER],
            care_provider_feature=CareProviderFeature.PATIENTS,
            care_provider_action=CareProviderPermissionAction.CREATE,
        )
    ),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
    plan_service: PlanComposerService = Depends(get_plan_composer_service),
) -> SuccessResponse[PlanGenerateResponse]:
    patient_id = await resolve_patient_access(
        actor=actor,
        patient_id=payload.user_id,
        care_provider_access_service=care_provider_access_service,
    )
    payload.user_id = patient_id
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
    actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[ProfileTypeEnum.PATIENT, ProfileTypeEnum.CARE_PROVIDER],
            care_provider_feature=CareProviderFeature.PATIENTS,
            care_provider_action=CareProviderPermissionAction.READ,
        )
    ),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
    plan_service: PlanComposerService = Depends(get_plan_composer_service),
) -> SuccessResponse[PlanDetailResponse]:
    patient_id = await resolve_patient_access(
        actor=actor,
        patient_id=user_id,
        care_provider_access_service=care_provider_access_service,
    )
    plan_details = await plan_service.get_current_plan_details(patient_id)
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
