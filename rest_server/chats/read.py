from datetime import datetime
from typing import List, Optional

from fastapi import Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from lib.core.constants import ProfileType
from lib.dependencies.auth.base import get_current_user
from lib.dependencies.database import get_postgres_session
from lib.dependencies.service_dependencies import (
    get_care_provider_profile_service, get_chat_service,
    get_patient_profile_service)
from lib.services.care_provider_service import CareProviderProfileService
from lib.services.chat_service import ChatService
from lib.services.patient_profile_service import PatientProfileService
from rest_server.response_models import SuccessResponse

from .router import router


@router.get("", response_model=SuccessResponse)
async def get_user_chats(
    request: Request,
    current_user=Depends(get_current_user),
    session: AsyncSession = Depends(get_postgres_session),
    chat_service: ChatService = Depends(get_chat_service),
    patient_profile_service: PatientProfileService = Depends(
        get_patient_profile_service
    ),
    care_provider_profile_service: CareProviderProfileService = Depends(
        get_care_provider_profile_service
    ),
):
    user_id, _ = current_user
    try:
        chats = await chat_service.fetch_user_chats(user_id, session)

        # Collect participant IDs by type
        patient_ids = {
            p["id"]
            for chat in chats
            for p in chat["participants"]
            if p["type"] == ProfileType.PATIENT.value
        }
        care_provider_ids = {
            p["id"]
            for chat in chats
            for p in chat["participants"]
            if p["type"] == ProfileType.CARE_PROVIDER.value
        }

        # Fetch profiles for patients from PostgreSQL
        patient_profiles = (
            await patient_profile_service.fetch_patient_profiles(
                list(patient_ids)
            )
        )

        # Fetch profiles for care providers from PostgreSQL
        care_provider_profiles = (
            await care_provider_profile_service.fetch_care_provider_profiles(
                list(care_provider_ids)
            )
        )

        # Merge profiles into chat participants
        for chat in chats:
            sender = chat.get("sender")
            if sender:
                if sender["type"] == ProfileType.PATIENT.value:
                    sender["profile"] = patient_profiles.get(sender["id"], {})
                else:
                    sender["profile"] = care_provider_profiles.get(
                        sender["id"], {}
                    )

            for receiver in chat.get("receivers", []):
                if receiver["type"] == ProfileType.PATIENT.value:
                    receiver["profile"] = patient_profiles.get(
                        receiver["id"], {}
                    )
                else:
                    receiver["profile"] = care_provider_profiles.get(
                        receiver["id"], {}
                    )

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
