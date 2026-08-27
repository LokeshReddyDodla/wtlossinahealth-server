"""Prepare (reshape a health-agent answer into a patient card) and send it into
the provider↔patient direct chat."""

from fastapi import Depends, status
from pydantic import BaseModel, Field

from lib.ai_foundation.agents.health_query import HealthQueryAgent
from lib.ai_foundation.agents.health_query.contracts import PatientAnswerCard
from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.service_dependencies import (
    get_care_provider_access_service,
    get_chat_management_service,
    get_chat_messaging_service,
    get_health_query_agent,
)
from lib.schemas.chat_message import ChatMessageCreate, MetadataSchema
from lib.services.care_provider_access_service import CareProviderAccessService
from lib.services.chat.chat_management_service import ChatManagementService
from lib.services.chat.chat_messaging_service import ChatMessagingService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse
from rest_server.v1.utils import resolve_patient_ids_for_query

from .router import router

_CARD_ROLES = [ProfileTypeEnum.CARE_PROVIDER, ProfileTypeEnum.ADMIN]


def _card_actor():
    return get_current_actor(
        allowed_roles=_CARD_ROLES,
        care_provider_feature=CareProviderFeature.PATIENTS,
        care_provider_action=CareProviderPermissionAction.READ,
    )


class PreparePatientCardRequest(BaseModel):
    patient_id: str = Field(description="Patient the card is for.")
    answer: str = Field(min_length=1, description="The health-agent answer to reshape.")


class SendPatientCardRequest(BaseModel):
    patient_id: str = Field(description="Patient to send the card to.")
    card: PatientAnswerCard = Field(description="The reviewed, provider-edited card.")


@router.post("/patient-card/prepare")
async def prepare_patient_card(
    payload: PreparePatientCardRequest,
    current_actor: Actor = Depends(_card_actor()),
    agent: HealthQueryAgent = Depends(get_health_query_agent),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    """Reshape a provider-facing answer into a patient-facing card for review."""
    await resolve_patient_ids_for_query(
        current_actor=current_actor,
        provided_patient_ids=[payload.patient_id],
        care_provider_access_service=care_provider_access_service,
    )
    card = await agent.reshape_to_patient_card(
        payload.answer, patient_id=payload.patient_id
    )
    return SuccessResponse(message="Card prepared", data=card)


@router.post("/patient-card/send")
async def send_patient_card(
    payload: SendPatientCardRequest,
    current_actor: Actor = Depends(_card_actor()),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
    chat_management_service: ChatManagementService = Depends(
        get_chat_management_service
    ),
    chat_messaging_service: ChatMessagingService = Depends(
        get_chat_messaging_service
    ),
):
    """Post the reviewed card into the provider↔patient direct chat."""
    await resolve_patient_ids_for_query(
        current_actor=current_actor,
        provided_patient_ids=[payload.patient_id],
        care_provider_access_service=care_provider_access_service,
    )

    chat_id = await chat_management_service.find_direct_chat(
        current_actor.id, payload.patient_id
    )
    if not chat_id:
        raise_http_exception(
            status_code=status.HTTP_404_NOT_FOUND,
            message="No direct chat exists with this patient yet.",
        )

    message = ChatMessageCreate(
        chat_id=chat_id,
        sender_id=current_actor.id,
        content=payload.card.takeaway,
        metadata=MetadataSchema(type="custom", status="sent"),
        card=payload.card.model_dump(),
    )
    await chat_messaging_service.add_message(message_data=message)
    return SuccessResponse(message="Card sent to patient")
