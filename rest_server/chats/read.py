from datetime import datetime
from typing import List, Optional

from fastapi import Depends, HTTPException, Query, Request

from lib.dependencies.auth.base import get_current_user
from lib.services.chat_service import ChatService
from rest_server.response_models import SuccessResponse

from .router import router


@router.get("", response_model=SuccessResponse)
async def get_user_chats(
    request: Request,
    current_user=Depends(get_current_user),
    chat_service: ChatService = Depends(ChatService),
):
    user_id, _ = current_user
    try:
        async with request.state.context.postgres_store.get_session() as session:
            chats = await chat_service.get_user_chats(user_id, session)

            return SuccessResponse(
                message="Chats fetched successfully",
                data=chats,
            )

    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch chats: {str(e)}"
        )


@router.get("/user-messages", response_model=SuccessResponse)
async def get_user_messages(
    request: Request,
    last_sync_time: Optional[datetime] = Query(None),
    current_user=Depends(get_current_user),
    chat_service: ChatService = Depends(ChatService),
):
    """
    Get all messages for a given user_id.
    """
    try:
        user_id, role = current_user
        messages = await chat_service.get_user_messages(
            user_id, last_sync_time
        )
        if not messages:
            raise HTTPException(status_code=404, detail="No messages found.")
        return SuccessResponse(
            message="Messages fetched successfully.", data=messages
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch messages: {str(e)}"
        )
