from fastapi import Depends, HTTPException, status
from fastapi.encoders import jsonable_encoder

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.service_dependencies import get_support_ticket_service
from lib.schemas.support_ticket import SupportTicketOpenRequest
from lib.services.support.support_ticket_service import SupportTicketService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.post("", response_model=SuccessResponse)
async def open_support_ticket(
    body: SupportTicketOpenRequest,
    actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[
                ProfileTypeEnum.PATIENT,
                ProfileTypeEnum.CARE_PROVIDER,
            ],
            check_permissions=False,
        )
    ),
    support_ticket_service: SupportTicketService = Depends(
        get_support_ticket_service
    ),
):
    try:
        requester_type = (
            "patient"
            if actor.role == ProfileTypeEnum.PATIENT
            else "care_provider"
        )
        ticket = await support_ticket_service.open_ticket(
            requester_id=actor.id,
            requester_type=requester_type,
            scope=body.scope,
            initial_message=body.initial_message,
            media=body.media,
            subject=body.subject,
            health_facility_id=body.health_facility_id,
        )
        return SuccessResponse(
            message="Support ticket opened.",
            data=jsonable_encoder(ticket),
        )
    except HTTPException as e:
        raise e
    except ValueError as e:
        raise_http_exception(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=str(e),
        )
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to open support ticket.",
            detail=str(e),
        )
