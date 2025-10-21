from typing import Optional
from fastapi import Depends, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from lib.dependencies.auth.base import get_current_user
from lib.dependencies.service_dependencies import (
    get_ai_conversation_service_v1,
)
from lib.services.ai_conversation_service_v1.ai_conversation_service_v1 import (
    AIConversationServiceV1,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse
from .router import router


@router.get(
    "/messages",
    response_model=SuccessResponse,
)
async def fetch_conversation_messages(
    request: Request,
    conversation_id: str,
    hidden_only: Optional[bool] = False,
    limit: Optional[int] = 100,
    offset: Optional[int] = 0,
    ai_conversation_service_v1: AIConversationServiceV1 = Depends(
        get_ai_conversation_service_v1
    ),
    current_user=Depends(get_current_user),
):
    try:
        messages = (
            await ai_conversation_service_v1.fetch_conversation_messages(
                conversation_id,
                hidden_only=hidden_only,
                limit=limit,
                offset=offset,
            )
        )
        encoded_messages = [jsonable_encoder(message) for message in messages]

        return SuccessResponse(
            message="Ai conversation messages fetched successfully.",
            data=encoded_messages,
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to fetch AI conversation messages.",
            detail=str(e),
        )
