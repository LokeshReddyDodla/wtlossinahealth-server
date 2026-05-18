from fastapi import Depends, HTTPException, status
from fastapi.encoders import jsonable_encoder

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
from lib.services.chat.message_enricher import attach_participant_profiles
from lib.services.patient_profile_service import PatientProfileService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.get("/{chat_id}", response_model=SuccessResponse)
async def get_single_chat(
    chat_id: str,
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
    """Single-chat fetch in the same shape as one element of ``GET /chats``.

    Participant-gated (404 if the user isn't in the chat — same response
    as 'chat doesn't exist' so we never leak existence). Used by the
    Flutter ``chat_list_updated{change=chat_created | participants_changed}``
    dispatch path to refetch one row instead of pulling the whole list.

    **Profile contract (spec item E):** every participant in the response
    (sender + receivers) is guaranteed to have a non-null ``profile``
    object with at least ``{first_name, last_name, profile_picture}``.
    For successfully resolved patient / care_provider rows the profile
    additionally carries the full PatientSchema / CareProviderSchema
    fields. For admins it's a synthesized ``Support Team`` placeholder.
    For unresolved users (deleted, race, stale chat doc) it's a
    synthesized ``Unknown User`` placeholder. Clients never need a
    fallback path.
    """
    user_id, _ = current_user
    try:
        chat = await chat_management_service.fetch_single_chat(
            chat_id, user_id
        )
        if not chat:
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="Chat not found.",
            )

        await attach_participant_profiles(
            [chat],
            patient_profile_service=patient_profile_service,
            care_provider_profile_service=care_provider_profile_service,
        )

        return SuccessResponse(data=jsonable_encoder(chat))

    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to fetch chat.",
            detail=str(e),
        )
