from typing import List, Tuple

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from lib.models.patient_smbg import PatientSMBG as PatientSMBGModel
from lib.schemas.patient_smbg import PatientSMBG as PatientSMBGSchema
from lib.schemas.patient_smbg import PatientSMBGCreate
from lib.services.ai_conversation_service import AiConversationService
from lib.services.patient_profile_service import PatientProfileService
from lib.utils.http_exceptions import raise_http_exception


class PatientSmbgService:
    def __init__(
        self,
        patient_profile_service: PatientProfileService,
        postgres_session: AsyncSession,
    ):
        self.postgres_session = postgres_session
        self.patient_profile_service = patient_profile_service
        self.ai_conversation_service = AiConversationService(
            conversation_type="smbg", model="gpt-4o-mini"
        )

    async def get_patient_smbgs(
        self, patient_id: str
    ) -> List[PatientSMBGModel]:
        try:
            result = await self.postgres_session.execute(
                select(PatientSMBGModel)
                .where(PatientSMBGModel.patient_id == patient_id)
                .order_by(PatientSMBGModel.reading_time.desc())
            )
            smbg_records = result.scalars().all()
            return list(smbg_records)
        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database error",
                detail=str(e),
            )

    async def upload_patient_smbg(
        self, patient_id: str, smbg_data: PatientSMBGCreate
    ) -> Tuple[PatientSMBGModel, bool]:
        try:
            new_smbg = PatientSMBGModel(
                patient_id=patient_id,
                glucose_level=smbg_data.glucose_level,
                reading_time=smbg_data.reading_time,
                source_name=smbg_data.source_name,
                source_platform=smbg_data.source_platform,
                type=smbg_data.type,
                notes=smbg_data.notes,
            )
            self.postgres_session.add(new_smbg)
            await self.postgres_session.commit()
            await self.postgres_session.refresh(new_smbg)

            ai_response_generated = await self._generate_ai_response(
                patient_id,
                str(new_smbg.id),
                new_smbg.glucose_level,
                new_smbg.reading_time,
            )

            return new_smbg, ai_response_generated

        except SQLAlchemyError as e:
            await self.postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    async def _generate_ai_response(
        self, patient_id, conversation_id, glucose_level, reading_time
    ):
        try:
            human_input = (
                f"I just recorded my blood sugar level, which was {glucose_level} mg/dL. "
                f"This reading was taken on {reading_time.strftime('%A, %B %d at %I:%M %p')}. "
                f"Could you provide some feedback or insights on this result?"
            )
            await self.ai_conversation_service.generate_response(
                patient_id=patient_id,
                conversation_id=conversation_id,
                human_input=human_input,
                conversation_type="smbg",
                patient_profile_service=self.patient_profile_service,
            )
            return True
        except Exception as e:
            print(f"Failed to generate AI response: {str(e)}")
            return False

    async def delete_smbg(self, smbg_id: str, patient_id: str):
        try:
            result = await self.postgres_session.execute(
                select(PatientSMBGModel).where(
                    PatientSMBGModel.id == smbg_id,
                    PatientSMBGModel.patient_id == patient_id,
                )
            )
            smbg_record = result.scalars().first()

            if not smbg_record:
                raise_http_exception(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message="SMBG record not found",
                )

            await self.postgres_session.delete(smbg_record)
            await self.postgres_session.commit()
        except SQLAlchemyError as e:
            await self.postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )
