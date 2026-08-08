from datetime import datetime
from typing import Optional

from fastapi import Depends, HTTPException, Query, Request, status

from lib.dependencies.auth.base import get_current_user
from lib.dependencies.service_dependencies import (
    get_care_provider_profile_service,
    get_chat_management_service,
    get_patient_profile_service,
)
from lib.services.care_provider_profile_service import (
    CareProviderProfileService,
)
from lib.services.chat.chat_management_service import ChatManagementService
from lib.services.chat.message_enricher import (
    attach_participant_profiles,
    enrich_messages_with_sender_profiles,
)
from lib.services.patient_profile_service import PatientProfileService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.get("", response_model=SuccessResponse)
async def get_user_chats(
    request: Request,
    current_user=Depends(get_current_user),
    chat_management_service: ChatManagementService = Depends(
        get_chat_management_service
    ),
    patient_profile_service: PatientProfileService = Depends(
        get_patient_profile_service
    ),
    care_provider_profile_service: CareProviderProfileService = Depends(
        get_care_provider_profile_service
    ),
):
    """List the authenticated user's chats.

    **Profile contract (spec item E):** every participant (sender +
    receivers) carries a non-null ``profile`` object. See
    ``GET /v1/chats/{chat_id}`` for the full contract — same guarantee.
    """
    user_id, _ = current_user
    try:
        chats = await chat_management_service.fetch_user_chats(user_id)
        await attach_participant_profiles(
            chats,
            patient_profile_service=patient_profile_service,
            care_provider_profile_service=care_provider_profile_service,
        )

        return SuccessResponse(
            message="Chats fetched successfully",
            data=chats,
        )

    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )


@router.get("/user-messages", response_model=SuccessResponse)
async def get_user_messages(
    request: Request,
    last_sync_time: Optional[datetime] = Query(None),
    current_user=Depends(get_current_user),
    chat_management_service: ChatManagementService = Depends(
        get_chat_management_service
    ),
):
    try:
        user_id, role = current_user
        messages = await chat_management_service.fetch_user_messages(
            user_id, last_sync_time
        )

        return SuccessResponse(
            message="Messages fetched successfully.", data=messages
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )


@router.get("/messages", response_model=SuccessResponse)
async def get_chat_messages(
    request: Request,
    chat_id: str,
    limit: int = Query(50, ge=1, le=100),
    before: Optional[str] = None,
    current_user=Depends(get_current_user),
    chat_management_service: ChatManagementService = Depends(
        get_chat_management_service
    ),
):
    try:
        user_id, role = current_user

        if not await chat_management_service.is_user_in_chat(
            chat_id=chat_id, user_id=user_id
        ):
            raise_http_exception(
                status_code=status.HTTP_403_FORBIDDEN,
                message="You don't have access to this chat.",
            )

        # Timestamps are stored naive-UTC; parse the cursor to match.
        before_dt = (
            datetime.fromisoformat(before.replace("Z", "")) if before else None
        )
        messages = await chat_management_service.fetch_chat_messages(
            chat_id, user_id, before=before_dt, limit=limit
        )
        messages = await enrich_messages_with_sender_profiles(messages)

        return SuccessResponse(
            message="Chat messages fetched successfully.", data=messages
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
