"""Care Intents — provider-authored guidance that shapes the AI's behavior.

A provider types one sentence ("keep reminding him to walk after dinner");
the structurer LLM fills every field; the provider confirms. Active intents
feed the proactive monitor and the health agent as attributed context.

Providers author independently (N per patient, each attributed); patients
see their active intents as friendly "care team focus areas".
"""

from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from lib.ai_foundation.care_intents.advisor import detect_intent_conflicts, propose_intents
from lib.ai_foundation.care_intents.contracts import CareIntentView, StructuredCareIntent
from lib.ai_foundation.care_intents.structurer import structure_care_intent
from lib.ai_foundation.models.gateway import ModelGateway
from lib.core.constants import ProfileTypeEnum
from lib.core.types import DEFAULT_AI_LANGUAGE
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.patient_access import resolve_patient_access
from lib.dependencies.service_dependencies import (
    get_care_intent_service,
    get_care_provider_access_service,
    get_insight_tracker,
    get_model_gateway,
)
from lib.models.care_intent import CareIntent
from lib.services.care_intent_service import CareIntentService
from lib.services.care_provider_access_service import CareProviderAccessService
from rest_server.response_models import SuccessResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/care-intents", tags=["Care Intents"])


# -- Schemas -------------------------------------------------------------------


class CareIntentCreateRequest(BaseModel):
    patient_id: UUID
    text: str = Field(..., min_length=5, max_length=1000, description="The instruction, as the provider would say it.")
    dry_run: bool = Field(
        default=False,
        description="Structure and return without saving — for the confirm/edit step.",
    )


class CareIntentStatusRequest(BaseModel):
    status: str = Field(..., pattern="^(active|paused|expired)$")


class CareIntentProposeRequest(BaseModel):
    patient_id: UUID


class CareIntentUpdateRequest(BaseModel):
    text: str = Field(..., min_length=5, max_length=1000)
    dry_run: bool = False


class FocusAreaItem(BaseModel):
    """Patient-facing view — friendly summary + who asked, nothing clinical."""

    care_intent_id: str
    author_name: str
    author_role: str
    summary: str
    since: str


def _raise_if_unsafe(structured: StructuredCareIntent) -> None:
    if structured.safety_flag:
        raise HTTPException(
            status_code=422,
            detail=(
                "This instruction looks like a clinical order (medication/dosing/"
                "diagnosis) and can't run as a nudge. "
                + (structured.safety_reason or "")
            ).strip(),
        )


def _view(i: CareIntent) -> CareIntentView:
    return CareIntentView(
        care_intent_id=str(i.care_intent_id),
        patient_id=str(i.patient_id),
        author_id=str(i.author_id),
        author_role=i.author_role,
        author_name=i.author_name,
        original_text=i.original_text,
        intent_type=i.intent_type,
        domain=i.domain,
        trigger_condition=i.trigger_condition,
        cadence=i.cadence,
        patient_summary=i.patient_summary,
        success_criteria=i.success_criteria,
        review_date=i.review_date,
        status=i.status,
        created_at=str(i.created_at),
    )


# -- Provider endpoints ---------------------------------------------------------


@router.post("", response_model=SuccessResponse[dict])
async def create_care_intent(
    payload: CareIntentCreateRequest,
    current_actor: Annotated[Actor, Depends(get_current_actor(
        allowed_roles=[ProfileTypeEnum.CARE_PROVIDER],
        check_permissions=False,
    ))],
    access: Annotated[CareProviderAccessService, Depends(get_care_provider_access_service)],
    service: Annotated[CareIntentService, Depends(get_care_intent_service)],
    gateway: Annotated[ModelGateway, Depends(get_model_gateway)],
):
    """Create (or dry-run structure) a care intent from one sentence."""
    verified_pid = await resolve_patient_access(
        actor=current_actor,
        patient_id=payload.patient_id,
        care_provider_access_service=access,
    )

    # Safety verdict comes from the server-side structurer ONLY — accepting a
    # client-supplied structure would let a forged safety_flag store a
    # clinical order.
    structured = await structure_care_intent(gateway, payload.text)
    _raise_if_unsafe(structured)

    # Advisory only — conflicts warn the provider, never block or resolve.
    conflicts: list[str] = []
    try:
        existing = await service.get_active_context(str(verified_pid))
        conflicts = await detect_intent_conflicts(
            gateway, new_text=payload.text, existing=existing,
        )
    except Exception:
        logger.warning("Conflict check failed — creating without warnings", exc_info=True)

    if payload.dry_run:
        return SuccessResponse(
            message="Structured (not saved)",
            data={
                "structured": structured.model_dump(mode="json"),
                "conflicts": conflicts,
            },
        )

    provider = current_actor.model
    intent = await service.create(
        patient_id=verified_pid,
        author_id=provider.care_provider_id,
        author_role=str(provider.role),
        author_name=provider.full_name,
        original_text=payload.text.strip(),
        structured=structured,
    )
    return SuccessResponse(
        message="Care intent created",
        data={
            "care_intent": _view(intent).model_dump(mode="json"),
            "conflicts": conflicts,
        },
    )


@router.post("/propose", response_model=SuccessResponse[dict])
async def propose_care_intents(
    payload: CareIntentProposeRequest,
    current_actor: Annotated[Actor, Depends(get_current_actor(
        allowed_roles=[ProfileTypeEnum.CARE_PROVIDER],
        check_permissions=False,
    ))],
    access: Annotated[CareProviderAccessService, Depends(get_care_provider_access_service)],
    service: Annotated[CareIntentService, Depends(get_care_intent_service)],
    gateway: Annotated[ModelGateway, Depends(get_model_gateway)],
    tracker: Annotated[object, Depends(get_insight_tracker)],
):
    """AI-drafted intent proposals from the patient's recent insights.

    Returns 0-2 grounded suggestions with rationale — NOTHING is stored;
    the provider approves one via the normal create flow.
    """
    verified_pid = await resolve_patient_access(
        actor=current_actor,
        patient_id=payload.patient_id,
        care_provider_access_service=access,
    )
    insights = await tracker.get_history(str(verified_pid), limit=15)
    existing = await service.get_active_context(str(verified_pid))
    proposals = await propose_intents(
        gateway, recent_insights=insights, existing=existing,
    )
    return SuccessResponse(
        message="OK",
        data={"proposals": [p.model_dump() for p in proposals]},
    )


@router.get("", response_model=SuccessResponse[dict])
async def list_care_intents(
    patient_id: UUID,
    current_actor: Annotated[Actor, Depends(get_current_actor(
        allowed_roles=[ProfileTypeEnum.CARE_PROVIDER, ProfileTypeEnum.ADMIN],
        check_permissions=False,
    ))],
    access: Annotated[CareProviderAccessService, Depends(get_care_provider_access_service)],
    service: Annotated[CareIntentService, Depends(get_care_intent_service)],
    include_inactive: bool = Query(False),
):
    """All intents for a patient — the whole care team sees each other's.

    Each intent carries its adherence report ("did what I asked happen"):
    daily verdicts, follow rate, barriers the data surfaced, and a
    needs_attention flag on repeated consecutive misses.
    """
    verified_pid = await resolve_patient_access(
        actor=current_actor,
        patient_id=patient_id,
        care_provider_access_service=access,
    )
    intents = await service.list_for_patient(verified_pid, include_inactive=include_inactive)
    adherence = await service.adherence_summary([i.care_intent_id for i in intents])
    return SuccessResponse(
        message="OK",
        data={
            "care_intents": [
                {
                    **_view(i).model_dump(mode="json"),
                    "adherence": adherence.get(str(i.care_intent_id)),
                }
                for i in intents
            ],
        },
    )


@router.put("/{care_intent_id}", response_model=SuccessResponse[dict])
async def update_care_intent(
    care_intent_id: UUID,
    payload: CareIntentUpdateRequest,
    current_actor: Annotated[Actor, Depends(get_current_actor(
        allowed_roles=[ProfileTypeEnum.CARE_PROVIDER],
        check_permissions=False,
    ))],
    access: Annotated[CareProviderAccessService, Depends(get_care_provider_access_service)],
    service: Annotated[CareIntentService, Depends(get_care_intent_service)],
    gateway: Annotated[ModelGateway, Depends(get_model_gateway)],
):
    """Edit an intent's instruction (author-only). Re-runs structuring, the
    safety gate, and the conflict check (against OTHER intents — an intent
    can't conflict with itself). Adherence history stays attached."""
    structured = await structure_care_intent(gateway, payload.text)
    _raise_if_unsafe(structured)

    existing_intent = await service.get_by_id(
        care_intent_id, author_id=current_actor.model.care_provider_id,
    )
    if existing_intent is None:
        raise HTTPException(status_code=404, detail="Care intent not found or not yours to edit")
    # Authorship isn't enough — a provider removed from the care team loses
    # write power over the patient's AI guidance.
    await resolve_patient_access(
        actor=current_actor,
        patient_id=existing_intent.patient_id,
        care_provider_access_service=access,
    )

    conflicts: list[str] = []
    try:
        others = [
            ci for ci in await service.get_active_context(str(existing_intent.patient_id))
            if ci["care_intent_id"] != str(care_intent_id)
        ]
        conflicts = await detect_intent_conflicts(
            gateway, new_text=payload.text, existing=others,
        )
    except Exception:
        logger.warning("Conflict check failed — updating without warnings", exc_info=True)

    if payload.dry_run:
        return SuccessResponse(
            message="Structured (not saved)",
            data={
                "structured": structured.model_dump(mode="json"),
                "conflicts": conflicts,
            },
        )

    intent = await service.update(
        care_intent_id,
        author_id=current_actor.model.care_provider_id,
        original_text=payload.text.strip(),
        structured=structured,
    )
    if intent is None:
        raise HTTPException(status_code=404, detail="Care intent not found or not yours to edit")
    return SuccessResponse(
        message="Care intent updated",
        data={
            "care_intent": _view(intent).model_dump(mode="json"),
            "conflicts": conflicts,
        },
    )


@router.delete("/{care_intent_id}", response_model=SuccessResponse[dict])
async def delete_care_intent(
    care_intent_id: UUID,
    current_actor: Annotated[Actor, Depends(get_current_actor(
        allowed_roles=[ProfileTypeEnum.CARE_PROVIDER],
        check_permissions=False,
    ))],
    access: Annotated[CareProviderAccessService, Depends(get_care_provider_access_service)],
    service: Annotated[CareIntentService, Depends(get_care_intent_service)],
):
    """Remove an intent and its adherence history — only the author deletes."""
    intent = await service.get_by_id(
        care_intent_id, author_id=current_actor.model.care_provider_id,
    )
    if intent is None:
        raise HTTPException(status_code=404, detail="Care intent not found or not yours to delete")
    await resolve_patient_access(
        actor=current_actor,
        patient_id=intent.patient_id,
        care_provider_access_service=access,
    )
    deleted = await service.delete(
        care_intent_id, author_id=current_actor.model.care_provider_id,
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Care intent not found or not yours to delete")
    return SuccessResponse(message="Care intent deleted", data={"deleted": True})


@router.patch("/{care_intent_id}/status", response_model=SuccessResponse[dict])
async def update_care_intent_status(
    care_intent_id: UUID,
    payload: CareIntentStatusRequest,
    current_actor: Annotated[Actor, Depends(get_current_actor(
        allowed_roles=[ProfileTypeEnum.CARE_PROVIDER],
        check_permissions=False,
    ))],
    access: Annotated[CareProviderAccessService, Depends(get_care_provider_access_service)],
    service: Annotated[CareIntentService, Depends(get_care_intent_service)],
):
    """Pause/resume/expire — only the author edits their own intent."""
    existing = await service.get_by_id(
        care_intent_id, author_id=current_actor.model.care_provider_id,
    )
    if existing is None:
        raise HTTPException(status_code=404, detail="Care intent not found or not yours to change")
    await resolve_patient_access(
        actor=current_actor,
        patient_id=existing.patient_id,
        care_provider_access_service=access,
    )
    intent = await service.update_status(
        care_intent_id,
        payload.status,
        author_id=current_actor.model.care_provider_id,
    )
    if intent is None:
        raise HTTPException(status_code=404, detail="Care intent not found or not yours to change")
    return SuccessResponse(
        message="Status updated",
        data={"care_intent": _view(intent).model_dump(mode="json")},
    )


# -- Patient endpoint ------------------------------------------------------------


@router.get("/focus-areas", response_model=SuccessResponse[list[FocusAreaItem]])
async def get_focus_areas(
    current_actor: Annotated[Actor, Depends(get_current_actor(
        allowed_roles=[ProfileTypeEnum.PATIENT],
        check_permissions=False,
    ))],
    service: Annotated[CareIntentService, Depends(get_care_intent_service)],
):
    """The patient's active care-team focus areas — transparency by design:
    the patient always sees what their care team asked the AI to focus on."""
    intents = await service.list_for_patient(current_actor.model.patient_id)

    summaries = [i.patient_summary for i in intents]
    language = await _preferred_language(str(current_actor.model.patient_id))
    if language != DEFAULT_AI_LANGUAGE and summaries:
        import asyncio

        from lib.ai_foundation.translation import TranslationService
        from lib.core.container import container

        translator = container.resolve(TranslationService)
        # Patient-specific content — the fixed-string cache is off-limits
        # (it is small, shared fleet-wide, and clears wholesale when full).
        summaries = list(await asyncio.gather(
            *(translator.translate(s, language) for s in summaries)
        ))

    items = [
        FocusAreaItem(
            care_intent_id=str(i.care_intent_id),
            author_name=i.author_name,
            author_role=i.author_role,
            summary=s,
            since=str(i.created_at.date() if i.created_at else ""),
        )
        for i, s in zip(intents, summaries)
    ]
    return SuccessResponse(message="OK", data=items)


async def _preferred_language(patient_id: str) -> str:
    from lib.ai_foundation.agents.core.patient_resolver import PatientNameResolver
    from lib.core.container import container

    try:
        resolver = container.resolve(PatientNameResolver)
        return await resolver.resolve_language(patient_id)
    except Exception:
        return DEFAULT_AI_LANGUAGE
