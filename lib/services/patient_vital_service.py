from typing import List, Tuple

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from lib.models.patient_vital import PatientVital as PatientVitalModel
from lib.schemas.patient_vital import PatientVital as PatientVitalSchema
from lib.schemas.patient_vital import PatientVitalCreate
from lib.services.patient_profile_service import PatientProfileService
from lib.utils.http_exceptions import raise_http_exception


class PatientVitalService:
    def __init__(
        self,
        patient_profile_service: PatientProfileService,
        postgres_session: AsyncSession,
    ):
        self.postgres_session = postgres_session
        self.patient_profile_service = patient_profile_service

    async def get_patient_vitals(
        self, patient_id: str
    ) -> List[PatientVitalModel]:
        try:
            result = await self.postgres_session.execute(
                select(PatientVitalModel)
                .where(PatientVitalModel.patient_id == patient_id)
                .order_by(PatientVitalModel.test_time.desc())
            )
            vitals_records = result.scalars().all()
            return list(vitals_records)
        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database error",
                detail=str(e),
            )

    async def upload_patient_vital(
        self, patient_id: str, vital_data: PatientVitalCreate
    ) -> PatientVitalModel:
        try:
            new_vital = PatientVitalModel(
                patient_id=patient_id,
                test_time=vital_data.test_time,
                a1c=vital_data.a1c,
                creatinine=vital_data.creatinine,
                diastolic_bp=vital_data.diastolic_bp,
                heart_rate=vital_data.heart_rate,
                ketones=vital_data.ketones,
                respiratory_rate=vital_data.respiratory_rate,
                spo2=vital_data.spo2,
                systolic_bp=vital_data.systolic_bp,
                temperature=vital_data.temperature,
                weight=vital_data.weight,
                source=vital_data.source,
            )

            self.postgres_session.add(new_vital)
            await self.postgres_session.commit()
            await self.postgres_session.refresh(new_vital)

            return new_vital

        except SQLAlchemyError as e:
            await self.postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    async def delete_vital(self, vital_id: str, patient_id: str):
        try:
            result = await self.postgres_session.execute(
                select(PatientVitalModel).where(
                    PatientVitalModel.id == vital_id,
                    PatientVitalModel.patient_id == patient_id,
                )
            )
            vital_record = result.scalars().first()

            if not vital_record:
                raise_http_exception(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message="Vital record not found",
                )

            await self.postgres_session.delete(vital_record)
            await self.postgres_session.commit()
        except SQLAlchemyError as e:
            await self.postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )
