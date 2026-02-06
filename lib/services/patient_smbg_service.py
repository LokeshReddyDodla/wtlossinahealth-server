from typing import List, Tuple

from fastapi import status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from lib.core.postgres_store import PostgresStore
from lib.models.patient_smbg import PatientSMBG as PatientSMBGModel
from lib.schemas.patient_smbg import PatientSMBGCreate
from lib.services.ai_conversation_service.ai_conversation_service import (
    AiConversationService,
)
from lib.services.patient_profile_service import PatientProfileService
from lib.services.vector import SMBGVectorService
from lib.utils.http_exceptions import raise_http_exception
from lib.utils.postgres_session_decorator import with_postgres_session
from lib.workers.tasks.smbg.enqueue import (
    enqueue_generate_smbg_vector_sync,
)


class PatientSmbgService:
    def __init__(
        self,
        postgres_store: PostgresStore,
        patient_profile_service: PatientProfileService,
        smbg_vector_service: SMBGVectorService,
    ):
        self.postgres_store = postgres_store
        self.patient_profile_service = patient_profile_service
        self.smbg_vector_service = smbg_vector_service
        self.ai_conversation_service = AiConversationService(
            conversation_type="smbg",
            selected_ai_model="gpt-4.1-mini",
            ai_model_provider="openai",
        )

    @with_postgres_session
    async def get_patient_smbgs(
        self, patient_id: str, *, postgres_session: AsyncSession
    ) -> List[PatientSMBGModel]:
        try:
            result = await postgres_session.execute(
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

    @with_postgres_session
    async def upload_patient_smbg(
        self,
        patient_id: str,
        smbg_data: PatientSMBGCreate,
        *,
        postgres_session: AsyncSession,
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
            postgres_session.add(new_smbg)
            await postgres_session.commit()
            await postgres_session.refresh(new_smbg)

            reading_data = {
                "glucose_mgdl": new_smbg.glucose_level,
                "reading_time": new_smbg.reading_time.isoformat(),
                "type": new_smbg.type,
                "notes": new_smbg.notes,
                "uploaded_at": new_smbg.uploaded_at,
                "source": new_smbg.source_name or "app",
            }
            enqueue_generate_smbg_vector_sync(
                patient_id=patient_id,
                reading_id=str(new_smbg.id),
                reading_data=reading_data,
            )

            ai_response_generated = await self._generate_ai_response(
                patient_id,
                str(new_smbg.id),
                new_smbg.glucose_level,
                new_smbg.reading_time,
            )

            return new_smbg, ai_response_generated

        except SQLAlchemyError as e:
            await postgres_session.rollback()
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
                user_id=patient_id,
                conversation_id=conversation_id,
                human_input=human_input,
                conversation_type="smbg",
            )
            return True
        except Exception as e:
            print(f"Failed to generate AI response: {str(e)}")
            return False

    @with_postgres_session
    async def delete_smbg(
        self, smbg_id: str, patient_id: str, *, postgres_session: AsyncSession
    ):
        try:
            result = await postgres_session.execute(
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

            await postgres_session.delete(smbg_record)
            await postgres_session.commit()
        except SQLAlchemyError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )
