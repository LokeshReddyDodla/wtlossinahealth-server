from datetime import datetime
from typing import List, Optional

from fastapi import Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from lib.dependencies.auth.base import get_current_user
from lib.dependencies.database import get_postgres_session
from lib.dependencies.service_dependencies import get_chat_service
from lib.services.chat_service import ChatService
from rest_server.response_models import SuccessResponse

from .router import router


@router.get("", response_model=SuccessResponse)
async def get_user_chats(
    request: Request,
    current_user=Depends(get_current_user),
    session: AsyncSession = Depends(get_postgres_session),
    chat_service: ChatService = Depends(get_chat_service),
):
    user_id, _ = current_user
    try:
        chats = await chat_service.fetch_user_chats(user_id, session)

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
    chat_service: ChatService = Depends(get_chat_service),
):
    """
    Get all messages for a given user_id.
    """
    try:
        user_id, role = current_user
        messages = await chat_service.fetch_user_messages(
            user_id, last_sync_time
        )

        return SuccessResponse(
            message="Messages fetched successfully.", data=messages
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch messages: {str(e)}"
        )
