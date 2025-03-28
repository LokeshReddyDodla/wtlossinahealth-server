
from fastapi import Depends, HTTPException, Request, status

from lib.dependencies.auth.base import get_current_user
from lib.dependencies.service_dependencies import get_chat_management_service
from lib.services.chat.chat_management_service import ChatManagementService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.patch("/toggle-pin-chat", response_model=SuccessResponse)
async def toggle_pin_chat(
    request: Request,
    chat_id: str,
    chat_management_service: ChatManagementService = Depends(
        get_chat_management_service
    ),
    current_user=Depends(get_current_user),
):
    """
    Send a message to a chat.
    """
    try:
        user_id, role = current_user

        await chat_management_service.toggle_pin_chat(
            chat_id=chat_id, participant_id=user_id
        )

        return SuccessResponse(message="Pin status toggled successfully.")
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to toggle pin chat.",
            detail=str(e),
        )
