import io
import json
from typing import Optional
from fastapi import Depends, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from lib.dependencies.auth.base import get_current_user
from lib.dependencies.auth.care_provider_auth import get_current_care_provider
from lib.dependencies.service_dependencies import (
    get_ai_conversation_service_v1,
)
from lib.services.ai_conversation_service_v1.ai_conversation_service_v1 import (
    AIConversationServiceV1,
)
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse
from lib.models.care_provider import CareProvider as CareProviderModel
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


@router.get("/export/download")
async def export_full_conversation_download(
    conversation_id: str,
    ai_conversation_service_v1: AIConversationServiceV1 = Depends(
        get_ai_conversation_service_v1
    ),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.READ,
            CareProviderFeature.AI_CHATS,
        )
    ),
):
    try:
        messages = (
            await ai_conversation_service_v1.fetch_conversation_messages(
                conversation_id=conversation_id,
                hidden_only=False,
            )
        )

        # Convert to JSON bytes
        json_bytes = io.BytesIO(json.dumps(messages, indent=2).encode("utf-8"))

        return StreamingResponse(
            json_bytes,
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="conversation_{conversation_id}.json"'
            },
        )

    except Exception as e:
        raise_http_exception(
            status_code=500,
            message="Failed to export conversation.",
            detail=str(e),
        )


@router.get("/export/message/{message_id}/download")
async def export_ai_message_download(
    message_id: str,
    ai_conversation_service_v1: AIConversationServiceV1 = Depends(
        get_ai_conversation_service_v1
    ),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.CREATE,
            CareProviderFeature.AI_CHATS,
        )
    ),
):
    try:
        message = await ai_conversation_service_v1.fetch_message_by_id(
            message_id
        )

        if not message or message["sender_type"] != "ai":
            raise_http_exception(
                status_code=404,
                message="AI message not found.",
                detail=f"No AI message with id {message_id}",
            )

        metadata = message.get("metadata", {})
        export_data = {
            "content": message.get("content"),
            "human_input": metadata.get("human_input"),
            "batched_contexts": metadata.get("batched_contexts", []),
        }

        json_bytes = io.BytesIO(
            json.dumps(export_data, indent=2).encode("utf-8")
        )

        return StreamingResponse(
            json_bytes,
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="ai_message_{message_id}.json"'
            },
        )

    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to export AI message.",
            detail=str(e),
        )
