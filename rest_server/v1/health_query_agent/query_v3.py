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
from lib.ai_foundation.agents.state import AgentContext, AgentInput, RequestPriority
from lib.ai_foundation.streaming.sse import SSE_RESPONSE_HEADERS
from lib.services.care_provider_access_service import CareProviderAccessService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from fastapi import HTTPException
from rest_server.response_models import SuccessResponse
from rest_server.v1.utils import resolve_patient_ids_for_query

from .router import router
from .api_schema import QueryRequest
from .utils import resolve_bot_conversation_id


def _resolve_agent_role(role: ProfileTypeEnum) -> str:
    """Map actor role to agent user_role string."""
    if role == ProfileTypeEnum.ADMIN:
        return "admin"
    if role == ProfileTypeEnum.CARE_PROVIDER:
        return "care_provider"
    return "patient"


def _resolve_priority(role: ProfileTypeEnum) -> RequestPriority:
    """Map actor role to request priority."""
    if role == ProfileTypeEnum.ADMIN:
        return RequestPriority.CRITICAL
    if role == ProfileTypeEnum.CARE_PROVIDER:
        return RequestPriority.HIGH
    return RequestPriority.NORMAL


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
            user_role=_resolve_agent_role(current_actor.role),
            thread_id=thread_id,
            patient_ids=resolved_patient_ids,
            priority=_resolve_priority(current_actor.role),
        ),
        stream=stream,
    )


def _check_rate_limit(current_actor: Actor, priority: RequestPriority) -> None:
    """Check rate limit and raise 429 if exceeded."""
    import logging
    import time as _time

    try:
        from lib.core.container import container
        from lib.ai_foundation.rate_limit.limiter import RateLimiter
        limiter: RateLimiter = container.resolve(RateLimiter)
        tenant_id = current_actor.id
        result = limiter.check(tenant_id, priority)
        if not result.allowed:
            retry_after = max(1, int(result.reset_at - _time.time()))
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded. Limit: {result.limit}/hour. Try again later.",
                headers={"Retry-After": str(retry_after)},
            )
        limiter.record(tenant_id, priority)
    except HTTPException:
        raise
    except (ConnectionError, TimeoutError, OSError) as exc:
        logging.getLogger(__name__).warning("Rate limiter unavailable: %s", exc)
    except Exception as exc:
        logging.getLogger(__name__).debug("Rate limiter error: %s", exc)


def _resolve_thread_id(current_actor: Actor, resolved_patient_ids: list[str]) -> str:
    """Resolve thread_id based on actor role and patient scope.

    Thread isolation:
    - Patient:              bot:patient:{patient_id}
    - Provider + 1 patient: bot:provider:{provider_id}:patient:{patient_id}
    - Provider + N patients: bot:provider:{provider_id}:group:{hash}
    - Admin + 1 patient:    bot:admin:{admin_id}:patient:{patient_id}
    - Admin + N patients:   bot:admin:{admin_id}:group:{hash}
    - Admin + 0 patients:   bot:admin:{admin_id}:general  (platform-wide questions)

    Care providers MUST always have patient_ids (enforced by resolve_patient_ids_for_query).
    """
    if current_actor.role == ProfileTypeEnum.PATIENT:
        return resolve_bot_conversation_id(
            actor_type="patient", actor_id=current_actor.id,
        )

    if len(resolved_patient_ids) == 1:
        return resolve_bot_conversation_id(
            actor_type=current_actor.role.value,
            actor_id=current_actor.id,
            subject_patient_id=resolved_patient_ids[0],
        )

    if len(resolved_patient_ids) > 1:
        import hashlib
        group_key = hashlib.sha256(
            ":".join(sorted(resolved_patient_ids)).encode()
        ).hexdigest()[:12]
        return f"bot:{current_actor.role.value}:{current_actor.id}:group:{group_key}"

    # Only admin can reach here (0 patients) — general platform questions
    return f"bot:{current_actor.role.value}:{current_actor.id}:general"


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
    _check_rate_limit(current_actor, priority)

    resolved_patient_ids = await resolve_patient_ids_for_query(
        current_actor=current_actor,
        provided_patient_ids=payload.patient_ids,
        care_provider_access_service=care_provider_access_service,
    )

    thread_id = _resolve_thread_id(current_actor, resolved_patient_ids)
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
    _check_rate_limit(current_actor, priority)

    resolved_patient_ids = await resolve_patient_ids_for_query(
        current_actor=current_actor,
        provided_patient_ids=payload.patient_ids,
        care_provider_access_service=care_provider_access_service,
    )

    thread_id = _resolve_thread_id(current_actor, resolved_patient_ids)
    input = _build_agent_input(
        payload, current_actor, resolved_patient_ids, thread_id, stream=True,
    )

    return StreamingResponse(
        agent.run_stream(input),
        media_type="text/event-stream",
        headers=SSE_RESPONSE_HEADERS,
    )
