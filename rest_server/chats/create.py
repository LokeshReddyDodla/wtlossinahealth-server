from typing import Literal, Union

from fastapi import APIRouter, Depends, HTTPException, Request

from lib.dependencies.auth.base import get_current_user
from lib.schemas.chat_message import ChatMessageCreate
from lib.services.chat_service import ChatService
from rest_server.response_models import ErrorResponse, SuccessResponse

from .router import router


@router.post("/send_message", response_model=SuccessResponse)
async def send_message(
    request: Request,
    message_data: ChatMessageCreate,
    current_user=Depends(get_current_user),
) -> Union[SuccessResponse, HTTPException]:
    """
    Send a message to a chat.
    """
    chat_service = ChatService()
    try:
        user_id, role = current_user

        # TODO: check if chat_id even exists
        await chat_service.add_message(
            message_data=message_data, user_id=str(user_id)
        )

        return SuccessResponse(message="Message sent successfully.")
    except HTTPException as e:
        raise e
    except Exception as e:
        response = ErrorResponse(
            message="Failed to send message", detail=str(e)
        )
        raise HTTPException(status_code=500, detail=response.dict())
