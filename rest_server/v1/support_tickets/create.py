from fastapi import Depends, HTTPException, status
from fastapi.encoders import jsonable_encoder

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.service_dependencies import (
    get_care_provider_profile_service,
    get_chat_management_service,
    get_patient_profile_service,
    get_support_ticket_service,
)
from lib.schemas.support_ticket import SupportTicketOpenRequest
from lib.services.care_provider_profile_service import (
    CareProviderProfileService,
)
from lib.services.chat.chat_management_service import ChatManagementService
from lib.services.chat.message_enricher import attach_participant_profiles
from lib.services.patient_profile_service import PatientProfileService
from lib.services.support.support_ticket_service import SupportTicketService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.post("", response_model=SuccessResponse)
async def open_support_ticket(
    body: SupportTicketOpenRequest,
    actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[
                ProfileTypeEnum.PATIENT,
                ProfileTypeEnum.CARE_PROVIDER,
            ],
            check_permissions=False,
        )
    ),
    support_ticket_service: SupportTicketService = Depends(
        get_support_ticket_service
    ),
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
    try:
        requester_type = (
            "patient"
            if actor.role == ProfileTypeEnum.PATIENT
            else "care_provider"
        )
        # Derive health_facility_id from the authenticated actor — NEVER
        # trust the body. Otherwise a patient at facility A could scope a
        # facility ticket to facility B, and B's support_staff would see it.
        # Body's health_facility_id only gates the schema validator now.
        actor_facility_id = getattr(actor.model, "health_facility_id", None)
        ticket = await support_ticket_service.open_ticket(
            requester_id=actor.id,
            requester_type=requester_type,
            scope=body.scope,
            initial_message=body.initial_message,
            media=body.media,
            subject=body.subject,
            health_facility_id=(
                str(actor_facility_id) if actor_facility_id else None
            ),
        )

        # Spec item G — embed the full chat record in the response so the
        # client can navigate to the thread immediately, no follow-up
        # GET /chats or ObjectBox polling. Same shape as one element of
        # GET /chats (participants enriched with PG profile data).
        chat = await chat_management_service.fetch_single_chat(
            ticket["chat_id"], actor.id
        )
        if chat is not None:
            await attach_participant_profiles(
                [chat],
                patient_profile_service=patient_profile_service,
                care_provider_profile_service=care_provider_profile_service,
            )
            ticket = {**ticket, "chat": chat}

        return SuccessResponse(
            message="Support ticket opened.",
            data=jsonable_encoder(ticket),
        )
    except HTTPException as e:
        raise e
    except ValueError as e:
        raise_http_exception(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=str(e),
        )
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to open support ticket.",
            detail=str(e),
        )
