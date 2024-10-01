from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from lib.dependencies.database import get_postgres_session
from lib.services.care_provider_profile_service import \
    CareProviderProfileService
from lib.services.chat_service import ChatService
from lib.services.patient_care_provider_service import \
    PatientCareProviderService
from lib.services.patient_profile_service import PatientProfileService
from lib.services.user_device_service import UserDeviceService


async def get_user_device_service(
    session: AsyncSession = Depends(get_postgres_session),
) -> UserDeviceService:
    return UserDeviceService(postgres_session=session)


async def get_chat_service(
    session: AsyncSession = Depends(get_postgres_session),
) -> ChatService:
    return ChatService()


async def get_care_provider_profile_service(
    session: AsyncSession = Depends(get_postgres_session),
    chat_service: ChatService = Depends(get_chat_service),
) -> CareProviderProfileService:
    return CareProviderProfileService(
        postgres_session=session, chat_service=chat_service
    )


async def get_patient_profile_service(
    session: AsyncSession = Depends(get_postgres_session),
    chat_service: ChatService = Depends(get_chat_service),
) -> PatientProfileService:
    return PatientProfileService(
        postgres_session=session, chat_service=chat_service
    )


async def get_patient_care_provider_service(
    session: AsyncSession = Depends(get_postgres_session),
    chat_service: ChatService = Depends(get_chat_service),
    care_provider_profile_service: CareProviderProfileService = Depends(
        get_care_provider_profile_service
    ),
    patient_service: PatientProfileService = Depends(
        get_patient_profile_service
    ),
) -> PatientCareProviderService:
    return PatientCareProviderService(
        postgres_session=session,
        chat_service=chat_service,
        care_provider_profile_service=care_provider_profile_service,
        patient_service=patient_service,
    )
