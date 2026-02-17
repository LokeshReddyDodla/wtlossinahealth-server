"""REST routes for the Profile Update micro-agent."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.service_dependencies import (
    get_profile_update_agent_service,
)
from lib.models.patient import Patient
from lib.schemas.profile_update_agent import (
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
        "profile fields conversationally.  Pass `conversation_id` to "
        "continue an existing conversation."
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
        conversation_id=body.conversation_id,
    )
    return SuccessResponse(data=result, message="Agent response")
