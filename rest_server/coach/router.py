"""Endpoints for the coach messenger nudges."""

from fastapi import APIRouter, Depends, status

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.patient_access import resolve_patient_access
from lib.dependencies.service_dependencies import (
    get_care_provider_access_service,
    get_coach_messenger_service,
)
from lib.schemas.weightloss_agent.coach import (
    CoachActionRequest,
    CoachActionResponse,
)
from lib.services.care_provider_access_service import CareProviderAccessService
from lib.services.weightloss_agent.coach_messenger_service import (
    CoachMessengerService,
)
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from rest_server.response_models import SuccessResponse

router = APIRouter(prefix="/coach", tags=["Coach"])


@router.post(
    "/act",
    response_model=SuccessResponse[CoachActionResponse],
    status_code=status.HTTP_200_OK,
)
async def coach_act(
    payload: CoachActionRequest,
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
    coach_service: CoachMessengerService = Depends(
        get_coach_messenger_service
    ),
) -> SuccessResponse[CoachActionResponse]:
    patient_id = await resolve_patient_access(
        actor=actor,
        patient_id=payload.user_id,
        care_provider_access_service=care_provider_access_service,
    )
    payload.user_id = patient_id
    response = await coach_service.act(payload)
    return SuccessResponse(
        message="Coach action prepared",
        data=response,
    )
