from fastapi import Depends, HTTPException, Request

from lib.dependencies.auth.base import get_current_user
from lib.schemas.chat import ChatSchema
from lib.services.chat_service import ChatService
from rest_server.chats.api_schema import ChatResponse

from .router import router


@router.get("", response_model=ChatResponse)
async def get_user_chats(
    request: Request, current_user=Depends(get_current_user)
):
    chat_service = ChatService()
    user_id, _ = current_user
    try:
        async with request.state.context.postgres_store.get_session() as session:
            chats = await chat_service.get_user_chats(user_id, session)

            return ChatResponse(
                message="Chats fetched successfully",
                data=ChatSchema.from_orm(chats),
            )

    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch chats: {str(e)}"
        )
