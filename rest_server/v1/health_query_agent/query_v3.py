"""
Health Query Agent v3 endpoints — foundation-native with SSE streaming.

Runs alongside the existing /query endpoint. The v3 endpoints use the
clean foundation agent with native streaming support.

Endpoints:
    POST /query/v3        — full response (non-streaming, backward-compatible)
    POST /query/v3/stream — SSE streaming (token-by-token)
"""

from fastapi import Depends
from starlette.responses import StreamingResponse

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.service_dependencies import (
    get_health_query_agent,
    get_care_provider_access_service,
)
from lib.ai_foundation.agents.health_query import HealthQueryAgent
from lib.ai_foundation.agents.state import AgentContext, AgentInput
from lib.ai_foundation.streaming.sse import SSE_RESPONSE_HEADERS
from lib.services.care_provider_access_service import CareProviderAccessService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from rest_server.response_models import SuccessResponse
from rest_server.v1.utils import resolve_patient_ids_for_query

from .router import router
from .api_schema import QueryRequest
from .utils import resolve_bot_conversation_id


def _build_agent_input(
    payload: QueryRequest,
    current_actor: Actor,
    resolved_patient_ids: list[str],
    thread_id: str,
    *,
    stream: bool = False,
) -> AgentInput:
    """Build AgentInput from the request context."""
    patient_id = None
    if current_actor.role == ProfileTypeEnum.PATIENT:
        patient_id = current_actor.id
    elif len(resolved_patient_ids) == 1:
        patient_id = resolved_patient_ids[0]

    return AgentInput(
        message=payload.message,
        context=AgentContext(
            patient_id=patient_id,
            user_id=current_actor.id,
            user_role=current_actor.role.value,
            thread_id=thread_id,
            patient_ids=resolved_patient_ids,
        ),
        stream=stream,
    )


@router.post("/query/v3")
async def process_query_v3(
    payload: QueryRequest,
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[ProfileTypeEnum.PATIENT, ProfileTypeEnum.CARE_PROVIDER],
            care_provider_feature=CareProviderFeature.PATIENTS,
            care_provider_action=CareProviderPermissionAction.READ,
        )
    ),
    agent: HealthQueryAgent = Depends(get_health_query_agent),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    """Process a health query using the foundation agent (non-streaming)."""
    resolved_patient_ids = await resolve_patient_ids_for_query(
        current_actor=current_actor,
        provided_patient_ids=payload.patient_ids,
        care_provider_access_service=care_provider_access_service,
    )

    subject_patient_id = None
    if current_actor.role == ProfileTypeEnum.CARE_PROVIDER and len(resolved_patient_ids) == 1:
        subject_patient_id = resolved_patient_ids[0]

    thread_id = resolve_bot_conversation_id(
        actor_type=current_actor.role.value,
        actor_id=current_actor.id,
        subject_patient_id=subject_patient_id,
    )

    input = _build_agent_input(payload, current_actor, resolved_patient_ids, thread_id)
    output = await agent.run(input)
    response = agent.to_query_response(input, output)

    return SuccessResponse(
        message="Query processed successfully",
        data=response,
    )


@router.post("/query/v3/stream")
async def process_query_v3_stream(
    payload: QueryRequest,
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[ProfileTypeEnum.PATIENT, ProfileTypeEnum.CARE_PROVIDER],
            care_provider_feature=CareProviderFeature.PATIENTS,
            care_provider_action=CareProviderPermissionAction.READ,
        )
    ),
    agent: HealthQueryAgent = Depends(get_health_query_agent),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    """Process a health query with SSE token streaming."""
    resolved_patient_ids = await resolve_patient_ids_for_query(
        current_actor=current_actor,
        provided_patient_ids=payload.patient_ids,
        care_provider_access_service=care_provider_access_service,
    )

    subject_patient_id = None
    if current_actor.role == ProfileTypeEnum.CARE_PROVIDER and len(resolved_patient_ids) == 1:
        subject_patient_id = resolved_patient_ids[0]

    thread_id = resolve_bot_conversation_id(
        actor_type=current_actor.role.value,
        actor_id=current_actor.id,
        subject_patient_id=subject_patient_id,
    )

    input = _build_agent_input(
        payload, current_actor, resolved_patient_ids, thread_id, stream=True,
    )

    return StreamingResponse(
        agent.run_stream(input),
        media_type="text/event-stream",
        headers=SSE_RESPONSE_HEADERS,
    )
