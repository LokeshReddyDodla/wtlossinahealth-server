"""REST routes for the Profile Update micro-agent."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.service_dependencies import (
    get_profile_update_agent_service,
)
from lib.models.patient import Patient
from lib.schemas.profile_update_agent import (
    DraftSummaryResponse,
    ProfileUpdateChatRequest,
    ProfileUpdateChatResponse,
)
from lib.services.profile_update_agent import ProfileUpdateAgentService
from rest_server.response_models import SuccessResponse

router = APIRouter(
    prefix="/profile-update-agent",
    tags=["Profile Update Agent"],
)


@router.post(
    "/chat",
    response_model=SuccessResponse[ProfileUpdateChatResponse],
    summary="Send a message to the profile-update agent",
    description=(
        "Multi-turn chat endpoint that helps the patient update their "
        "profile fields conversationally.  The active draft is resolved "
        "automatically from the authenticated patient — no conversation ID "
        "is needed."
    ),
)
async def chat(
    body: ProfileUpdateChatRequest,
    current_patient: Patient = Depends(get_current_patient),
    service: ProfileUpdateAgentService = Depends(
        get_profile_update_agent_service
    ),
) -> SuccessResponse[ProfileUpdateChatResponse]:
    result = await service.chat(
        patient_id=str(current_patient.patient_id),
        message=body.message,
    )
    return SuccessResponse(data=result, message="Agent response")


@router.get(
    "/draft",
    response_model=SuccessResponse[Optional[DraftSummaryResponse]],
    summary="Get the active profile-update draft",
    description=(
        "Returns the current active draft for the authenticated patient, "
        "or null if no draft is in progress."
    ),
)
async def get_draft(
    current_patient: Patient = Depends(get_current_patient),
    service: ProfileUpdateAgentService = Depends(
        get_profile_update_agent_service
    ),
) -> SuccessResponse[Optional[DraftSummaryResponse]]:
    draft = await service.get_active_draft(
        patient_id=str(current_patient.patient_id),
    )
    return SuccessResponse(
        data=draft,
        message="Active draft retrieved" if draft else "No active draft",
    )
