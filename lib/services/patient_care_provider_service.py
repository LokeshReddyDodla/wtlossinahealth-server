from typing import Any, List, Optional

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from lib.core.constants import EmitMessageKey, ProfileType
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.models.patient import Patient as PatientModel
from lib.models.patient_care_provider import \
    PatientCareProvider as PatientCareProviderModel
from lib.schemas.care_provider import CareProvider as CareProviderSchema
from lib.schemas.chat import ParticipantSchema
from lib.schemas.patient import Patient as PatientSchema
from lib.schemas.patient_care_provider import \
    PatientCareProvider as PatientCareProviderSchema
from lib.services.care_provider_profile_service import \
    CareProviderProfileService
from lib.services.chat_service import ChatService
from lib.services.patient_profile_service import PatientProfileService
from lib.services.socketio_service import sio


class PatientCareProviderService:
    def __init__(
        self,
        postgres_session: AsyncSession,
        chat_service: ChatService,
        care_provider_profile_service: CareProviderProfileService,
        patient_profile_service: PatientProfileService,
    ):
        self.postgres_session = postgres_session
        self.chat_service = chat_service
        self.care_provider_profile_service = care_provider_profile_service
        self.patient_profile_service = patient_profile_service

    async def check_existing_connection(
        self, patient_id: str, care_provider_id: str
    ) -> PatientCareProviderModel:
        stmt = select(PatientCareProviderModel).filter_by(
            patient_id=patient_id, care_provider_id=care_provider_id
        )
        result = await self.postgres_session.execute(stmt)
        return result.scalars().first()

    async def fetch_patient_care_provider(
        self, patient_care_provider_id: str, detailed: bool = False
    ) -> PatientCareProviderModel:

        try:
            stmt = select(PatientCareProviderModel).where(
                PatientCareProviderModel.patient_care_provider_id
                == patient_care_provider_id
            )

            if detailed:
                stmt = stmt.options(
                    selectinload(PatientCareProviderModel.patient),
                    selectinload(PatientCareProviderModel.care_provider),
                )

            result = await self.postgres_session.execute(stmt)
            patient_care_provider = result.scalars().first()

            if not patient_care_provider:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Patient care provider association not found.",
                )

            return patient_care_provider

        except SQLAlchemyError as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database error: {str(e)}",
            )

    @staticmethod
    async def fetch_associated_records(
        postgres_session: AsyncSession,
        patient_id: Optional[str] = None,
        care_provider_id: Optional[str] = None,
        patient_care_provider_id: Optional[str] = None,
    ) -> List[PatientCareProviderModel]:
        try:
            if (
                not patient_id
                and not care_provider_id
                and not patient_care_provider_id
            ):
                raise ValueError(
                    "Either patient_id or care_provider_id or patient_care_provider_id must be provided."
                )

            stmt = select(PatientCareProviderModel).options(
                selectinload(PatientCareProviderModel.patient),
                selectinload(PatientCareProviderModel.care_provider),
            )

            if patient_care_provider_id:
                stmt = stmt.filter(
                    PatientCareProviderModel.patient_care_provider_id
                    == patient_care_provider_id
                )

            elif patient_id:
                stmt = stmt.filter(
                    PatientCareProviderModel.patient_id == patient_id
                )
            elif care_provider_id:
                stmt = stmt.filter(
                    PatientCareProviderModel.care_provider_id
                    == care_provider_id
                )

            result = await postgres_session.execute(stmt)
            connected_records = result.scalars().all()

            return list(connected_records)

        except SQLAlchemyError as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database error: {str(e)}",
            )
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
            )

    async def create_patient_care_provider(
        self, patient_care_provider_data
    ) -> PatientCareProviderModel:
        try:
            existing_connection = await self.check_existing_connection(
                patient_care_provider_data.patient_id,
                patient_care_provider_data.care_provider_id,
            )
            if existing_connection:
                return existing_connection

            new_patient_care_provider = PatientCareProviderModel(
                **patient_care_provider_data.dict()
            )
            self.postgres_session.add(new_patient_care_provider)

            care_provider = (
                await self.care_provider_profile_service.fetch_care_provider(
                    patient_care_provider_data.care_provider_id
                )
            )

            patient = await self.patient_profile_service.fetch_patient_profile(
                patient_care_provider_data.patient_id
            )

            await self.postgres_session.commit()
            await self.postgres_session.refresh(new_patient_care_provider)

            # Create chat instance in MongoDB
            await self._create_chats(patient, care_provider)

            await self.chat_service.notify_participants(
                message_key=EmitMessageKey.CHAT_LIST_UPDATED.value,
                user_id=patient_care_provider_data.patient_id,
            )

            return new_patient_care_provider
        except IntegrityError:
            raise HTTPException(
                status_code=400,
                detail="Patient care provider association already exists.",
            )
        except SQLAlchemyError as e:
            raise HTTPException(
                status_code=500, detail=f"Database Error: {str(e)}"
            )

    async def update_patient_care_provider(
        self, patient_care_provider_id: str, updates: dict
    ) -> PatientCareProviderModel:
        try:
            patient_care_provider = await self.fetch_patient_care_provider(
                patient_care_provider_id
            )

            for key, value in updates.items():
                setattr(patient_care_provider, key, value)

            self.postgres_session.add(patient_care_provider)
            await self.postgres_session.commit()
            await self.postgres_session.refresh(patient_care_provider)

            await self.chat_service.notify_participants(
                message_key=EmitMessageKey.CHAT_LIST_UPDATED.value,
                user_id=str(patient_care_provider.patient_id),
            )

            return patient_care_provider

        except IntegrityError:
            await self.postgres_session.rollback()
            raise HTTPException(
                status_code=400,
                detail="Update conflicts with existing associations.",
            )
        except SQLAlchemyError as e:
            await self.postgres_session.rollback()
            raise HTTPException(status_code=500, detail=str(e))

    async def delete_patient_care_provider(
        self, patient_care_provider_id: str
    ):
        try:
            patient_care_provider: PatientCareProviderModel = (
                await self.fetch_patient_care_provider(
                    patient_care_provider_id
                )
            )

            # Additional cleanup logic, e.g., delete associated chats
            await self.chat_service.delete_direct_chat(
                str(patient_care_provider.patient_id),
                str(patient_care_provider.care_provider_id),
            )

            await self.postgres_session.delete(patient_care_provider)
            await self.postgres_session.commit()

            await self.chat_service.notify_participants(
                message_key=EmitMessageKey.CHAT_LIST_UPDATED.value,
                user_id=str(patient_care_provider.patient_id),
            )

        except SQLAlchemyError as e:
            await self.postgres_session.rollback()
            raise HTTPException(status_code=500, detail=str(e))

    async def _create_chats(
        self, patient: PatientSchema, care_provider: CareProviderSchema
    ):

        chat_id = await self.chat_service.create_new_chat(
            user_id=str(patient.patient_id),
            type=ProfileType.PATIENT.value,
            is_group=False,
            is_read_only=False,
            is_muted=False,
            is_archived=False,
            is_pinned=False,
        )

        await self.chat_service.add_participant_in_chat(
            chat_id=chat_id,
            user_id=str(care_provider.care_provider_id),
            type=ProfileType.CARE_PROVIDER.value,
            is_read_only=False,
            is_muted=False,
            is_archived=False,
            is_pinned=False,
        )

        group_chat = await self.chat_service.find_group_chat_for_patient(
            patient_id=str(patient.patient_id)
        )
        if group_chat:
            await self.chat_service.add_participant_in_chat(
                chat_id=group_chat["_id"],
                user_id=str(care_provider.care_provider_id),
                type=ProfileType.CARE_PROVIDER.value,
            )
