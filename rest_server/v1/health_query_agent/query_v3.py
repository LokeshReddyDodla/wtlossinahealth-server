"""
Health Query Agent v3 endpoints — foundation-native with SSE streaming.

Runs alongside the existing /query endpoint. The v3 endpoints use the
clean foundation agent with native streaming support.

Supports all roles: Patient, Care Provider, and Admin.
Admin can query across all patients/facilities without access restrictions.

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
from lib.ai_foundation.agents.thread_utils import resolve_thread_id as _foundation_resolve_thread_id

from .router import router
from .api_schema import QueryRequest
from .utils import enforce_rate_limit, resolve_priority as _resolve_priority


def _resolve_agent_role(role: ProfileTypeEnum) -> str:
    """Map actor role to agent user_role string.

    Auth role ADMIN maps to query persona 'research' — infrastructure
    admin privileges (config, thread bypass) stay at the REST layer.
    """
    if role == ProfileTypeEnum.ADMIN:
        return "research"
    if role == ProfileTypeEnum.CARE_PROVIDER:
        return "care_provider"
    return "patient"


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

    metadata: dict = {}
    if payload.tier:
        metadata["tier"] = payload.tier
    if payload.metadata:
        metadata.update(payload.metadata)
    if payload.local_time:
        metadata["local_time"] = payload.local_time

    return AgentInput(
        message=payload.message,
        context=AgentContext(
            patient_id=patient_id,
            user_id=current_actor.id,
            user_role=_resolve_agent_role(current_actor.role),
            thread_id=thread_id,
            patient_ids=resolved_patient_ids,
            priority=_resolve_priority(current_actor.role),
            refs=payload.refs,
            metadata=metadata,
        ),
        stream=stream,
    )


def _resolve_thread_id(current_actor: Actor, resolved_patient_ids: list[str]) -> str:
    """Resolve thread_id — delegates to the single source of truth."""
    return _foundation_resolve_thread_id(
        role=current_actor.role.value,
        actor_id=current_actor.id,
        patient_ids=resolved_patient_ids,
    )


@router.post("/query/v3")
async def process_query_v3(
    payload: QueryRequest,
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[
                ProfileTypeEnum.PATIENT,
                ProfileTypeEnum.CARE_PROVIDER,
                ProfileTypeEnum.ADMIN,
            ],
            care_provider_feature=CareProviderFeature.PATIENTS,
            care_provider_action=CareProviderPermissionAction.READ,
        )
    ),
    agent: HealthQueryAgent = Depends(get_health_query_agent),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    """Process a health query using the foundation agent (non-streaming).

    Roles:
    - Patient: queries own data only
    - Care Provider: queries assigned patients (patient_ids required)
    - Admin: queries any patient(s) across all facilities
    """
    priority = _resolve_priority(current_actor.role)
    enforce_rate_limit(current_actor, priority)

    resolved_patient_ids = await resolve_patient_ids_for_query(
        current_actor=current_actor,
        provided_patient_ids=payload.patient_ids,
        care_provider_access_service=care_provider_access_service,
    )

    thread_id = _resolve_thread_id(current_actor, resolved_patient_ids)
    agent_input = _build_agent_input(payload, current_actor, resolved_patient_ids, thread_id)
    output = await agent.run(agent_input)
    response = agent.to_query_response(agent_input, output)

    return SuccessResponse(
        message="Query processed successfully",
        data=response,
    )


@router.post("/query/v3/stream")
async def process_query_v3_stream(
    payload: QueryRequest,
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[
                ProfileTypeEnum.PATIENT,
                ProfileTypeEnum.CARE_PROVIDER,
                ProfileTypeEnum.ADMIN,
            ],
            care_provider_feature=CareProviderFeature.PATIENTS,
            care_provider_action=CareProviderPermissionAction.READ,
        )
    ),
    agent: HealthQueryAgent = Depends(get_health_query_agent),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    """Process a health query with SSE token streaming.

    Roles:
    - Patient: queries own data only
    - Care Provider: queries assigned patients (patient_ids required)
    - Admin: queries any patient(s) across all facilities
    """
    priority = _resolve_priority(current_actor.role)
    enforce_rate_limit(current_actor, priority)

    resolved_patient_ids = await resolve_patient_ids_for_query(
        current_actor=current_actor,
        provided_patient_ids=payload.patient_ids,
        care_provider_access_service=care_provider_access_service,
    )

    thread_id = _resolve_thread_id(current_actor, resolved_patient_ids)
    agent_input = _build_agent_input(
        payload, current_actor, resolved_patient_ids, thread_id, stream=True,
    )

    return StreamingResponse(
        agent.run_stream(agent_input),
        media_type="text/event-stream",
        headers=SSE_RESPONSE_HEADERS,
    )
