from fastapi import Depends, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder

from lib.dependencies.auth.base import get_current_user
from lib.dependencies.service_dependencies import get_ai_conversation_service
from lib.services.ai_conversation_service import AiConversationService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.get("", response_model=SuccessResponse)
async def get_ai_conversation_messages(
    request: Request,
    conversation_id: str,
    ai_conversation_service: AiConversationService = Depends(
        get_ai_conversation_service
    ),
    current_user=Depends(get_current_user),
):
    try:
        messages = await ai_conversation_service.fetch_conversation_messages(
            conversation_id, return_raw=True, for_frontend=True
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
