from typing import Optional

from fastapi import Depends, HTTPException, Query, status
from fastapi.encoders import jsonable_encoder

from lib.core.types import SupportScopeLiteral, SupportTicketStatusLiteral
from lib.dependencies.auth.support_agent import (
    SupportAgent,
    get_support_agent_actor,
)
from lib.dependencies.service_dependencies import get_support_ticket_service
from lib.schemas.support_ticket import RequesterTypeLiteral
from lib.services.support.support_ticket_service import SupportTicketService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.get("", response_model=SuccessResponse)
async def list_queue(
    scope: Optional[SupportScopeLiteral] = Query(None),
    status_filter: Optional[SupportTicketStatusLiteral] = Query(
        None, alias="status"
    ),
    requester_type: Optional[RequesterTypeLiteral] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    agent: SupportAgent = Depends(get_support_agent_actor),
    support_ticket_service: SupportTicketService = Depends(
        get_support_ticket_service
    ),
):
    try:
        tickets = await support_ticket_service.list_queue(
            agent_scopes=agent.allowed_scopes,
            agent_facility_ids=agent.facility_ids,
            scope_filter=scope,
            status_filter=status_filter,
            requester_type_filter=requester_type,
            limit=limit,
            offset=offset,
        )
        return SuccessResponse(data=jsonable_encoder(tickets))
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to list support queue.",
            detail=str(e),
        )


@router.get("/{ticket_id}", response_model=SuccessResponse)
async def get_ticket(
    ticket_id: str,
    agent: SupportAgent = Depends(get_support_agent_actor),
    support_ticket_service: SupportTicketService = Depends(
        get_support_ticket_service
    ),
):
    """Returns the ticket plus its full message thread. Agents call this
    BEFORE replying, so the message read here is scope-gated (not
    participant-gated) — they're not yet a chat participant."""
    try:
        ticket = await support_ticket_service.get_ticket_with_messages_for_agent(
            ticket_id=ticket_id,
            agent_scopes=agent.allowed_scopes,
            agent_facility_ids=agent.facility_ids,
        )
        if not ticket:
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="Ticket not found or out of your scope.",
            )
        return SuccessResponse(data=jsonable_encoder(ticket))
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to fetch ticket.",
            detail=str(e),
        )
