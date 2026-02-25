"""REST routes for the Profile Update micro-agent."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, Query

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.service_dependencies import (
    get_profile_update_agent_service,
)
from lib.models.patient import Patient
from lib.schemas.profile_update_agent import (
    ConversationListResponse,
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


@router.get(
    "/conversations",
    response_model=SuccessResponse[List[ConversationListResponse]],
    summary="List profile-update conversations",
    description=(
        "Returns a paginated list of the patient's profile-update "
        "conversations, sorted by most recently updated first."
    ),
)
async def list_conversations(
    limit: int = Query(20, ge=1, le=100, description="Max items to return"),
    skip: int = Query(0, ge=0, description="Number of items to skip"),
    current_patient: Patient = Depends(get_current_patient),
    service: ProfileUpdateAgentService = Depends(
        get_profile_update_agent_service
    ),
) -> SuccessResponse[List[ConversationListResponse]]:
    conversations = await service.list_conversations(
        patient_id=str(current_patient.patient_id),
        limit=limit,
        skip=skip,
    )
    return SuccessResponse(
        data=conversations,
        message="Conversations retrieved successfully",
    )
