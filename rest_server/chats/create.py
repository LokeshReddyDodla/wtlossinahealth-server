from typing import Literal, Union

from fastapi import APIRouter, Depends, HTTPException, Request

from lib.dependencies.auth.base import get_current_user
from lib.services.chat_service import ChatService
from rest_server.chats.api_schema import ChatMessageCreate
from rest_server.response_models import ErrorResponse, SuccessResponse

from .router import router


@router.post("/send_message", response_model=SuccessResponse)
async def send_message(
    request: Request,
    chat_id: str,
    message: ChatMessageCreate,
    chat_type: Literal["individual", "group"] = "individual",
    current_user=Depends(get_current_user),
) -> Union[SuccessResponse, HTTPException]:
    """
    Send a message to a chat.
    """
    chat_service = ChatService()
    try:
        await chat_service.add_message(
            chat_id=chat_id, message=message, chat_type=chat_type
        )

        return SuccessResponse(message="Message sent successfully.")

    except Exception as e:
        response = ErrorResponse(
            message="Failed to send message", detail=str(e)
        )
        raise HTTPException(status_code=500, detail=response.dict())
