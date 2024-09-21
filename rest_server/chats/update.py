from typing import Literal, Union

from fastapi import APIRouter, Depends, HTTPException, Request

from lib.dependencies.auth.base import get_current_user
from lib.schemas.chat_message import ChatMessageCreate
from lib.services.chat_service import ChatService
from rest_server.response_models import ErrorResponse, SuccessResponse

from .router import router


@router.post("/toggle-pin-chat", response_model=SuccessResponse)
async def toggle_pin_chat(
    request: Request,
    chat_id: str,
    current_user=Depends(get_current_user),
) -> Union[SuccessResponse, HTTPException]:
    """
    Send a message to a chat.
    """
    chat_service = ChatService()
    try:
        user_id, role = current_user

        await chat_service.toggle_pin_chat(
            chat_id=chat_id, participant_id=user_id
        )

        return SuccessResponse(message="Pin status toggled successfully.")
    except HTTPException as e:
        raise e
    except Exception as e:
        response = ErrorResponse(
            message="Failed to toggle pin chat.", detail=str(e)
        )
        raise HTTPException(status_code=500, detail=response.dict())
