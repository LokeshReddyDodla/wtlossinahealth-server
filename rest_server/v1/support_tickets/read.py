from typing import Optional

from fastapi import Depends, HTTPException, Query, status
from fastapi.encoders import jsonable_encoder

from lib.core.constants import ProfileTypeEnum
from lib.core.types import SupportTicketStatusLiteral
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.service_dependencies import get_support_ticket_service
from lib.services.support.support_ticket_service import SupportTicketService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


_REQUESTER_ROLES = [
    ProfileTypeEnum.PATIENT,
    ProfileTypeEnum.CARE_PROVIDER,
]


@router.get("/mine", response_model=SuccessResponse)
async def list_my_tickets(
    status_filter: Optional[SupportTicketStatusLiteral] = Query(
        None, alias="status"
    ),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    actor: Actor = Depends(
        get_current_actor(
            allowed_roles=_REQUESTER_ROLES, check_permissions=False
        )
    ),
    support_ticket_service: SupportTicketService = Depends(
        get_support_ticket_service
    ),
):
    try:
        tickets, total = await support_ticket_service.list_tickets_for_requester(
            requester_id=actor.id,
            status_filter=status_filter,
            limit=limit,
            offset=offset,
        )
        return SuccessResponse(data=jsonable_encoder({
            "tickets": tickets,
            "total": total,
        }))
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to list tickets.",
            detail=str(e),
        )


@router.get("/{ticket_id}", response_model=SuccessResponse)
async def get_my_ticket(
    ticket_id: str,
    actor: Actor = Depends(
        get_current_actor(
            allowed_roles=_REQUESTER_ROLES, check_permissions=False
        )
    ),
    support_ticket_service: SupportTicketService = Depends(
        get_support_ticket_service
    ),
):
    try:
        ticket = await support_ticket_service.get_ticket_for_requester(
            ticket_id=ticket_id, requester_id=actor.id
        )
        if not ticket:
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="Ticket not found.",
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
