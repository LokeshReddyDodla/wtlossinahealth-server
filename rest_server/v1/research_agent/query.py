"""
POST /research-agent/query — cohort research question (SSE streaming).

Phase 1 surface:
    {
        "question": "Who has hypo events AND less than 6 hours of sleep this week?",
        "cohort": {"kind": "ids", "ids": ["uuid1", "uuid2", ...]}
    }

Phase 1 enforces:
    - Only CARE_PROVIDER and ADMIN roles may call.
    - All cohort patient IDs must be accessible to the calling care provider
      (admins see everything in their facility, validated by the access service).
    - cohort.kind must be "ids" — "saved" and "panel" return 501 until the
      saved-cohort collection and panel lookup ship in Phase 2.

The response is a Server-Sent Event stream emitting the standard foundation
event types (status, intent, tool_call, tool_result, token, done) so
existing UI infrastructure works without changes.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

from lib.ai_foundation.agents.research_agent import (
    CohortRef,
    CohortRefKind,
    HistoryTurn,
    ResearchAgent,
    ResearchInput,
)
from lib.ai_foundation.agents.health_query.provider_panel_utils import has_partial_access
from lib.core.constants import AIFeatureEnum
from lib.services.ai_feature_toggle_service import (
    actor_facility_id,
    ai_feature_toggle_service,
)
from lib.ai_foundation.streaming.sse import SSE_RESPONSE_HEADERS
from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.service_dependencies import (
    get_care_provider_access_service,
    get_research_agent,
)
from lib.services.care_provider_access_service import CareProviderAccessService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)

from .router import router

logger = logging.getLogger(__name__)


# ── Request schema ───────────────────────────────────────────────────────────


class CohortRefRequest(BaseModel):
    """How the caller is identifying the cohort."""

    kind: str = Field(
        description="One of: 'ids' (Phase 1), 'saved' (Phase 2), 'panel' (Phase 2).",
    )
    ids: list[str] | None = Field(
        default=None,
        description="Explicit patient UUIDs. Required when kind='ids'.",
    )
    cohort_id: str | None = Field(
        default=None,
        description="Saved-cohort identifier. Required when kind='saved'.",
    )


class HistoryTurnRequest(BaseModel):
    """One prior turn — client-supplied. The frontend tracks the chat thread
    in its own state and sends the most recent turns with each request so the
    agent can resolve references like 'those 17' to the previous cohort."""

    role: str = Field(description="'user' or 'assistant'.")
    content: str = Field(min_length=1)


class ResearchQueryRequest(BaseModel):
    question: str = Field(min_length=1, description="The provider's research question.")
    cohort: CohortRefRequest = Field(description="Cohort to research over.")
    history: list[HistoryTurnRequest] = Field(
        default_factory=list,
        description=(
            "Prior conversation turns (most recent last), oldest first. "
            "Caller should cap to ~6 turns for cost / latency reasons."
        ),
    )


# ── Endpoint ─────────────────────────────────────────────────────────────────


@router.post(
    "/query",
    summary="Cohort research question (SSE streaming).",
)
async def post_research_query(
    payload: ResearchQueryRequest,
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[ProfileTypeEnum.CARE_PROVIDER, ProfileTypeEnum.ADMIN],
            # Researching across patient data requires the PATIENTS feature
            # with READ permission — same scope as /v1/patients itself, which
            # is how the cohort gets resolved client-side.
            care_provider_feature=CareProviderFeature.PATIENTS,
            care_provider_action=CareProviderPermissionAction.READ,
        )
    ),
    agent: ResearchAgent = Depends(get_research_agent),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    """Stream a cohort research answer as Server-Sent Events.

    Phase 1: only ``cohort.kind == 'ids'`` is supported. Saved cohorts
    and panel-wide queries return 501.
    """
    await ai_feature_toggle_service.require_facility(
        AIFeatureEnum.RESEARCH_AGENT, actor_facility_id(current_actor)
    )
    cohort_kind = payload.cohort.kind.strip().lower()

    if cohort_kind == "ids":
        if not payload.cohort.ids:
            raise HTTPException(
                status_code=400,
                detail="cohort.ids is required when cohort.kind == 'ids'.",
            )
        patient_ids = await _resolve_and_check_ids(
            raw_ids=payload.cohort.ids,
            current_actor=current_actor,
            access_service=care_provider_access_service,
        )
        cohort_ref = CohortRef(kind=CohortRefKind.IDS, ids=patient_ids)

    elif cohort_kind == "saved":
        raise HTTPException(
            status_code=501,
            detail=(
                "Saved cohorts require the ai_cohorts collection (Phase 2). "
                "Pass explicit cohort.ids for now."
            ),
        )

    elif cohort_kind == "panel":
        raise HTTPException(
            status_code=501,
            detail=(
                "Whole-panel cohorts require CareProviderAccessService."
                "get_all_assigned_patients (pending decision). "
                "Pass explicit cohort.ids for now."
            ),
        )

    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported cohort.kind: {payload.cohort.kind!r}.",
        )

    history = [
        HistoryTurn(role=t.role, content=t.content)
        for t in (payload.history or [])
        if t.role in ("user", "assistant")
    ]
    research_input = ResearchInput(
        question=payload.question,
        cohort=cohort_ref,
        provider_id=str(current_actor.id),
        history=history,
    )

    return StreamingResponse(
        agent.run_stream(research_input),
        media_type="text/event-stream",
        headers=SSE_RESPONSE_HEADERS,
    )


# ── Helpers ──────────────────────────────────────────────────────────────────


async def _resolve_and_check_ids(
    *,
    raw_ids: list[str],
    current_actor: Actor,
    access_service: CareProviderAccessService,
) -> list[str]:
    """Parse UUIDs and enforce access control. Returns the validated str-IDs."""
    try:
        patient_uuids = [UUID(pid) for pid in raw_ids]
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid patient ID format — expected UUID.",
        ) from exc

    if current_actor.role == ProfileTypeEnum.CARE_PROVIDER:
        accessible = await access_service.get_accessible_patients(
            care_provider_id=UUID(current_actor.id),
            patient_ids=patient_uuids,
        )
        if has_partial_access(len(patient_uuids), len(accessible)):
            raise HTTPException(
                status_code=403,
                detail="Access denied for one or more requested patients.",
            )

    return [str(pid) for pid in patient_uuids]
