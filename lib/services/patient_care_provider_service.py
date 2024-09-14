from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from fastapi import HTTPException, status
from lib.models.patient import Patient
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.schemas.care_provider import CareProvider as CareProviderSchema
from lib.models.patient_care_provider import (
    PatientCareProvider as PatientCareProviderModel,
)
from lib.schemas.patient_care_provider import (
    PatientCareProvider as PatientCareProviderSchema,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from lib.services.care_provider_service import CareProviderService
from lib.services.chat_service import ChatService
from sqlalchemy.orm import selectinload

from lib.services.patient_profile_service import PatientService


class PatientCareProviderService:
    def __init__(self, postgres_session: AsyncSession):
        self.postgres_session = postgres_session
        self.chat_service = ChatService()
        self.care_provider_service = CareProviderService(postgres_session)
        self.patient_service = PatientService(postgres_session)

    async def check_existing_connection(
        self, patient_id: str, care_provider_id: str
    ):
        stmt = select(PatientCareProviderModel).filter_by(
            patient_id=patient_id, care_provider_id=care_provider_id
        )
        result = await self.postgres_session.execute(stmt)
        return result.scalars().first()

    async def fetch_patient_care_provider(
        self, patient_care_provider_id: str, detailed: bool = False
    ) -> PatientCareProviderSchema:

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

            return PatientCareProviderSchema.from_orm(patient_care_provider)

        except SQLAlchemyError as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database error: {str(e)}",
            )

    async def create_patient_care_provider(
        self, patient_care_provider_data
    ) -> PatientCareProviderSchema:
        try:
            existing_connection = await self.check_existing_connection(
                patient_care_provider_data.patient_id,
                patient_care_provider_data.care_provider_id,
            )
            if existing_connection:
                return PatientCareProviderSchema.from_orm(existing_connection)

            new_patient_care_provider = PatientCareProviderModel(
                **patient_care_provider_data.dict()
            )
            self.postgres_session.add(new_patient_care_provider)

            care_provider = (
                await self.care_provider_service.fetch_care_provider(
                    patient_care_provider_data.care_provider_id
                )
            )

            patient = await self.patient_service.fetch_patient_profile(
                patient_care_provider_data.patient_id
            )

            await self.postgres_session.commit()
            await self.postgres_session.refresh(new_patient_care_provider)

            # Create chat instance in MongoDB
            await self._create_chats(patient, care_provider)

            return PatientCareProviderSchema.from_orm(
                new_patient_care_provider
            )
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
    ) -> PatientCareProviderSchema:
        try:
            patient_care_provider = self.fetch_patient_care_provider(
                patient_care_provider_id
            )

            for key, value in updates.items():
                setattr(patient_care_provider, key, value)

            self.postgres_session.add(patient_care_provider)
            await self.postgres_session.commit()
            await self.postgres_session.refresh(patient_care_provider)

            return PatientCareProviderSchema.from_orm(patient_care_provider)

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
            patient_care_provider: PatientCareProviderSchema = (
                await self.fetch_patient_care_provider(
                    patient_care_provider_id
                )
            )

            # Additional cleanup logic, e.g., delete associated chats
            await self.chat_service.delete_related_chats(
                str(patient_care_provider.patient_id)
            )

            await self.postgres_session.delete(patient_care_provider)
            await self.postgres_session.commit()

            return "Patient care provider association deleted successfully."

        except SQLAlchemyError as e:
            await self.postgres_session.rollback()
            raise HTTPException(status_code=500, detail=str(e))

    async def _create_chats(
        self, patient: Patient, care_provider: CareProviderSchema
    ):
        participants = [
            {
                "id": str(patient.patient_id),
                "type": "patient",
                "name": f"{patient.first_name} {patient.last_name}",
            },
            {
                "id": str(care_provider.care_provider_id),
                "type": "care_provider",
                "name": f"{care_provider.first_name} {care_provider.last_name}",
                "role": care_provider.role,
            },
        ]
        await self.chat_service.create_chat_instance(participants=participants)

        group_chat = await self.chat_service.find_group_chat_for_patient(
            patient_id=str(patient.patient_id)
        )
        if group_chat:
            await self.chat_service.add_care_provider_to_group(
                group_chat_id=group_chat["_id"],
                care_provider_id=str(care_provider.care_provider_id),
                care_provider_name=f"{care_provider.first_name} {care_provider.last_name}",
                role=care_provider.role,
            )
