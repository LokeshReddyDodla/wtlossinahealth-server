from fastapi import Depends, HTTPException, status
from fastapi.encoders import jsonable_encoder

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.service_dependencies import get_support_ticket_service
from lib.services.support.support_ticket_service import SupportTicketService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.post("/{ticket_id}/close", response_model=SuccessResponse)
async def close_my_ticket(
    ticket_id: str,
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
        ticket = await support_ticket_service.close_ticket_by_requester(
            ticket_id=ticket_id, requester_id=actor.id
        )
        if not ticket:
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="Ticket not found.",
            )
        return SuccessResponse(
            message="Ticket closed.", data=jsonable_encoder(ticket)
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to close ticket.",
            detail=str(e),
        )
