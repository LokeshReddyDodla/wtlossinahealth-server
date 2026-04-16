"""REST routes for the patient onboarding chat agent."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.service_dependencies import (
    get_patient_onboarding_agent_service,
)
from lib.models.patient import Patient
from lib.schemas.patient_onboarding_agent import (
    OnboardingSessionSummaryResponse,
    PatientOnboardingChatRequest,
    PatientOnboardingChatResponse,
    PatientOnboardingStartRequest,
)
from lib.services.patient_onboarding_agent import PatientOnboardingAgentService
from rest_server.response_models import SuccessResponse

router = APIRouter(
    prefix="/patient-onboarding-agent",
    tags=["Patient Onboarding Agent"],
)


@router.post(
    "/start",
    response_model=SuccessResponse[PatientOnboardingChatResponse],
    summary="Start or resume patient onboarding",
)
async def start_onboarding(
    body: PatientOnboardingStartRequest,
    current_patient: Patient = Depends(get_current_patient),
    service: PatientOnboardingAgentService = Depends(
        get_patient_onboarding_agent_service
    ),
) -> SuccessResponse[PatientOnboardingChatResponse]:
    result = await service.start(
        patient_id=str(current_patient.patient_id),
        restart=body.restart,
    )
    return SuccessResponse(data=result, message="Onboarding agent ready")


@router.post(
    "/chat",
    response_model=SuccessResponse[PatientOnboardingChatResponse],
    summary="Send a message to the onboarding agent",
)
async def chat(
    body: PatientOnboardingChatRequest,
    current_patient: Patient = Depends(get_current_patient),
    service: PatientOnboardingAgentService = Depends(
        get_patient_onboarding_agent_service
    ),
) -> SuccessResponse[PatientOnboardingChatResponse]:
    result = await service.chat(
        patient_id=str(current_patient.patient_id),
        message=body.message,
    )
    return SuccessResponse(data=result, message="Onboarding agent response")


@router.get(
    "/session",
    response_model=SuccessResponse[Optional[OnboardingSessionSummaryResponse]],
    summary="Get the active onboarding session",
)
async def get_session(
    current_patient: Patient = Depends(get_current_patient),
    service: PatientOnboardingAgentService = Depends(
        get_patient_onboarding_agent_service
    ),
) -> SuccessResponse[Optional[OnboardingSessionSummaryResponse]]:
    result = await service.get_active_session(
        patient_id=str(current_patient.patient_id),
    )
    return SuccessResponse(
        data=result,
        message="Active onboarding session retrieved" if result else "No active onboarding session",
    )
