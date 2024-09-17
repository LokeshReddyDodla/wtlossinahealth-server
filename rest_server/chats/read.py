from fastapi import Depends, HTTPException, Request

from lib.dependencies.auth.base import get_current_user
from lib.services.chat_service import ChatService

from .router import router


@router.get("")
async def get_user_chats(
    request: Request, current_user=Depends(get_current_user)
):
    chat_service = ChatService()
    user_id, _ = current_user
    try:
        chats = await chat_service.get_user_chats(
            user_id, fetch_all_messages=True
        )
        return chats

    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch chats: {str(e)}"
        )
