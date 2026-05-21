"""REST routes for the unified Profile Agent."""

from __future__ import annotations

from typing import Optional

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.service_dependencies import get_profile_agent_service
from lib.models.patient import Patient
from lib.schemas.profile_agent import (
    GapReport,
    ProfileAgentChatRequest,
    ProfileAgentChatResponse,
    ProfileAgentStartRequest,
    SessionSummaryResponse,
)
from lib.services.profile_agent import ProfileAgentService

from rest_server.response_models import SuccessResponse

router = APIRouter(
    prefix="/profile-agent",
    tags=["Profile Agent"],
)


@router.post(
    "/start",
    response_model=SuccessResponse[ProfileAgentChatResponse],
    summary="Start or resume a profile-agent session",
)
async def start_session(
    body: ProfileAgentStartRequest,
    current_patient: Patient = Depends(get_current_patient),
    service: ProfileAgentService = Depends(get_profile_agent_service),
) -> SuccessResponse[ProfileAgentChatResponse]:
    result = await service.start(
        patient_id=str(current_patient.patient_id),
        restart=body.restart,
    )
    return SuccessResponse(data=result, message="Profile agent ready")


@router.post(
    "/chat",
    response_model=SuccessResponse[ProfileAgentChatResponse],
    summary="Send a turn to the profile agent",
)
async def chat(
    body: ProfileAgentChatRequest,
    current_patient: Patient = Depends(get_current_patient),
    service: ProfileAgentService = Depends(get_profile_agent_service),
) -> SuccessResponse[ProfileAgentChatResponse]:
    result = await service.chat(
        patient_id=str(current_patient.patient_id),
        message=body.message,
    )
    return SuccessResponse(data=result, message="Profile agent response")


@router.get(
    "/session",
    response_model=SuccessResponse[Optional[SessionSummaryResponse]],
    summary="Get the active profile-agent session",
)
async def get_session(
    current_patient: Patient = Depends(get_current_patient),
    service: ProfileAgentService = Depends(get_profile_agent_service),
) -> SuccessResponse[Optional[SessionSummaryResponse]]:
    result = await service.get_active_session(
        patient_id=str(current_patient.patient_id),
    )
    return SuccessResponse(
        data=result,
        message="Active session retrieved" if result else "No active session",
    )


@router.get(
    "/gaps",
    response_model=SuccessResponse[GapReport],
    summary="Report profile completeness and next missing fields",
)
async def get_gaps(
    current_patient: Patient = Depends(get_current_patient),
    service: ProfileAgentService = Depends(get_profile_agent_service),
) -> SuccessResponse[GapReport]:
    result = await service.get_gaps(
        patient_id=str(current_patient.patient_id),
    )
    return SuccessResponse(data=result, message="Profile gap report")
