from uuid import UUID

from fastapi import Depends, HTTPException, status

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.patient_access import resolve_patient_access
from lib.dependencies.service_dependencies import (
    get_agent_meal_v1_service,
    get_care_provider_access_service,
)
from lib.schemas.agent_meal_v1 import MealAgentRequest, MealAgentResponseData
from lib.services.agent_meal_v1 import AgentMealV1Service
from lib.services.care_provider_access_service import CareProviderAccessService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.post("/respond", response_model=SuccessResponse[MealAgentResponseData])
async def respond_meal_agent(
    payload: MealAgentRequest,
    service: AgentMealV1Service = Depends(get_agent_meal_v1_service),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[
                ProfileTypeEnum.ADMIN,
                ProfileTypeEnum.CARE_PROVIDER,
                ProfileTypeEnum.PATIENT,
            ],
            care_provider_feature=CareProviderFeature.PATIENTS,
            care_provider_action=CareProviderPermissionAction.READ,
        )
    ),
):
    try:
        target_patient_id = await resolve_patient_access(
            actor=current_actor,
            patient_id=UUID(str(payload.patient_id)),
            care_provider_access_service=care_provider_access_service,
        )
        payload.patient_id = target_patient_id
        if current_actor.role == ProfileTypeEnum.PATIENT:
            payload.audience = "patient"
        response = await service.respond(payload)
        return SuccessResponse(
            message="Meal agent response generated successfully",
            data=response,
        )
    except HTTPException as exc:
        raise exc
    except Exception as exc:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to generate meal agent response",
            detail=str(exc),
        )
