from fastapi import Depends, HTTPException, status
from fastapi.encoders import jsonable_encoder

from lib.dependencies.auth.support_agent import (
    SupportAgent,
    get_support_agent_actor,
)
from lib.dependencies.service_dependencies import get_support_ticket_service
from lib.schemas.support_ticket import (
    SupportAgentReplyRequest,
    SupportTicketStatusUpdateRequest,
)
from lib.services.support.support_ticket_service import SupportTicketService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.post("/{ticket_id}/reply", response_model=SuccessResponse)
async def reply_to_ticket(
    ticket_id: str,
    body: SupportAgentReplyRequest,
    agent: SupportAgent = Depends(get_support_agent_actor),
    support_ticket_service: SupportTicketService = Depends(
        get_support_ticket_service
    ),
):
    try:
        ticket = await support_ticket_service.agent_reply(
            ticket_id=ticket_id,
            agent_id=agent.id,
            agent_role=agent.role,
            agent_scopes=agent.allowed_scopes,
            agent_facility_ids=agent.facility_ids,
            content=body.content,
            media=body.media,
        )
        if not ticket:
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="Ticket not found or out of your scope.",
            )
        return SuccessResponse(
            message="Reply sent.", data=jsonable_encoder(ticket)
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to send reply.",
            detail=str(e),
        )


@router.patch("/{ticket_id}/status", response_model=SuccessResponse)
async def change_ticket_status(
    ticket_id: str,
    body: SupportTicketStatusUpdateRequest,
    agent: SupportAgent = Depends(get_support_agent_actor),
    support_ticket_service: SupportTicketService = Depends(
        get_support_ticket_service
    ),
):
    try:
        ticket = await support_ticket_service.change_status(
            ticket_id=ticket_id,
            agent_scopes=agent.allowed_scopes,
            agent_facility_ids=agent.facility_ids,
            new_status=body.status,
        )
        if not ticket:
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="Ticket not found or out of your scope.",
            )
        return SuccessResponse(
            message="Status updated.", data=jsonable_encoder(ticket)
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to update status.",
            detail=str(e),
        )
