from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime, timedelta
from lib.models.patient import Patient as PatientModel
from lib.models.patient_smbg import PatientSMBG as PatientSMBGModel
from lib.dependencies.database import get_async_postgres_session
from lib.utils.http_exceptions import raise_http_exception


class SMBGMetricsService:
    async def get_active_patients(
        self,
        health_facility_id: str,
        days: int = 3,
    ) -> list[PatientModel]:
        async with get_async_postgres_session() as session:
            try:
                threshold = datetime.now() - timedelta(days=days)

                stmt = (
                    select(PatientModel)
                    .join(
                        PatientSMBGModel,
                        PatientModel.patient_id == PatientSMBGModel.patient_id,
                    )
                    .where(
                        PatientSMBGModel.uploaded_at >= threshold,
                        PatientModel.health_facility_id == health_facility_id,
                    )
                    .group_by(PatientModel.patient_id)
                    .options(selectinload(PatientModel.smbgs))
                )

                result = await session.execute(stmt)
                return list(result.scalars().all())

            except SQLAlchemyError as e:
                raise_http_exception(
                    status_code=500,
                    message="Failed to fetch active SMBG patients",
                    detail=str(e),
                )
