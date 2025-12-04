"""Endpoints for the coach messenger nudges."""

from fastapi import APIRouter, Depends, status

from lib.dependencies.service_dependencies import (
    get_coach_messenger_service,
)
from lib.schemas.weightloss_agent.coach import (
    CoachActionRequest,
    CoachActionResponse,
)
from lib.services.weightloss_agent.coach_messenger_service import (
    CoachMessengerService,
)
from rest_server.response_models import SuccessResponse

router = APIRouter(prefix="/coach", tags=["Coach"])


@router.post(
    "/act",
    response_model=SuccessResponse[CoachActionResponse],
    status_code=status.HTTP_200_OK,
)
async def coach_act(
    payload: CoachActionRequest,
    coach_service: CoachMessengerService = Depends(
        get_coach_messenger_service
    ),
) -> SuccessResponse[CoachActionResponse]:
    response = await coach_service.act(payload)
    return SuccessResponse(
        message="Coach action prepared",
        data=response,
    )
