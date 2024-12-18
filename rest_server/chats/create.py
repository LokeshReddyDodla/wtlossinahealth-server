from typing import Literal, Union

from fastapi import APIRouter, Depends, HTTPException, Request, status

from lib.dependencies.auth.base import get_current_user
from lib.dependencies.service_dependencies import get_chat_messaging_service
from lib.schemas.chat_message import ChatMessageCreate
from lib.services.chat.chat_messaging_service import ChatMessagingService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import ErrorResponse, SuccessResponse

from .router import router


@router.post("/send_message", response_model=SuccessResponse)
async def send_message(
    request: Request,
    message_data: ChatMessageCreate,
    current_user=Depends(get_current_user),
    chat_messaging_service: ChatMessagingService = Depends(get_chat_messaging_service),
):
    try:
        user_id, role = current_user

        # TODO: check if chat_id even exists
        await chat_messaging_service.add_message(
            message_data=message_data,
        )

        return SuccessResponse(message="Message sent successfully.")
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to send message.",
            detail=str(e),
        )
