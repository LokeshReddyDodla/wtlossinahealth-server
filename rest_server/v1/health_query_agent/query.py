from fastapi import Depends

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.service_dependencies import get_health_query_agent_service
from lib.services.health_query_agent.service import HealthQueryAgentService
from lib.services.health_query_agent.schemas import QueryResponse
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from rest_server.response_models import SuccessResponse
from rest_server.v1.utils import resolve_patient_ids_for_query

from .router import router
from .api_schema import QueryRequest
from .utils import resolve_bot_conversation_id


@router.post(
    "/query",
    response_model=SuccessResponse[QueryResponse],
)
async def process_query(
    payload: QueryRequest,
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[
                ProfileTypeEnum.PATIENT,
                ProfileTypeEnum.CARE_PROVIDER,
            ],
            care_provider_feature=CareProviderFeature.PATIENTS,
            care_provider_action=CareProviderPermissionAction.READ,
        )
    ),
    agent_service: HealthQueryAgentService = Depends(get_health_query_agent_service),
):
    user_id = current_actor.id
    user_role = current_actor.role

    resolved_patient_ids = resolve_patient_ids_for_query(
        current_actor=current_actor,
        provided_patient_ids=payload.patient_ids,
    )

    subject_patient_id = None
    if (
        current_actor.role == ProfileTypeEnum.CARE_PROVIDER
        and len(resolved_patient_ids) == 1
    ):
        subject_patient_id = resolved_patient_ids[0]

    thread_id = resolve_bot_conversation_id(
        actor_type=current_actor.role.value,
        actor_id=user_id,
        subject_patient_id=subject_patient_id,
    )
    response = await agent_service.process_message(
        user_message=payload.message,
        thread_id=thread_id,
        user_id=user_id,
        user_role=user_role.value,
        patient_ids=resolved_patient_ids,
    )

    return SuccessResponse(
        message="Query processed successfully",
        data=response,
    )
