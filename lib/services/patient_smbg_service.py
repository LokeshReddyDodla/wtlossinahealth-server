from typing import List

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from lib.models.patient_smbg import PatientSMBG as PatientSMBGModel
from lib.schemas.patient_smbg import PatientSMBG as PatientSMBGSchema
from lib.schemas.patient_smbg import PatientSMBGCreate


class PatientSmbgService:
    def __init__(self, postgres_session: AsyncSession):
        self.postgres_session = postgres_session

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
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database error: {str(e)}",
            )

    async def upload_patient_smbg(
        self, patient_id: str, smbg_data: PatientSMBGCreate
    ) -> PatientSMBGModel:
        try:
            new_smbg = PatientSMBGModel(
                patient_id=patient_id,
                glucose_level=smbg_data.glucose_level,
                reading_time=smbg_data.reading_time,
                source=smbg_data.source,
                type=smbg_data.type,
                notes=smbg_data.notes,
            )
            self.postgres_session.add(new_smbg)
            await self.postgres_session.commit()
            await self.postgres_session.refresh(new_smbg)
            return new_smbg
        except SQLAlchemyError as e:
            await self.postgres_session.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database Error: {str(e)}",
            )

    async def delete_smbg(self, smbg_id: str, patient_id: str):
        try:
            result = await self.postgres_session.execute(
                select(PatientSMBGModel).where(
                    PatientSMBGModel.smbg_id == smbg_id,
                    PatientSMBGModel.patient_id == patient_id,
                )
            )
            smbg_record = result.scalars().first()

            if not smbg_record:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="SMBG record not found.",
                )

            await self.postgres_session.delete(smbg_record)
            await self.postgres_session.commit()
        except SQLAlchemyError as e:
            await self.postgres_session.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database Error: {str(e)}",
            )
