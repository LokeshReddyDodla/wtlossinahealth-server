from uuid import UUID
from typing import Optional

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.services.chat.chat_management_service import ChatManagementService


class DirectChatResolver:
    def __init__(self, chat_service: ChatManagementService):
        self.chat_service = chat_service

    async def resolve(
        self,
        *,
        actor: Actor,
        patient_id: UUID,
        care_providers: list[CareProviderModel] | None = None,
    ) -> Optional[str]:
        if actor.role == ProfileTypeEnum.ADMIN:
            return None

        if actor.role == ProfileTypeEnum.CARE_PROVIDER:
            if not isinstance(actor.model, CareProviderModel):
                return None

            return await self.chat_service.find_direct_chat(
                str(patient_id),
                str(actor.model.care_provider_id),
            )

        if actor.role == ProfileTypeEnum.PATIENT and care_providers:
            for cp in care_providers:
                chat_id = await self.chat_service.find_direct_chat(
                    str(patient_id),
                    str(cp.care_provider_id),
                )
                if chat_id:
                    return chat_id

        return None
