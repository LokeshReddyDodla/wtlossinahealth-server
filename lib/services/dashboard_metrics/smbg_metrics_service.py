from typing import Optional
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime, timedelta
from lib.models.associations import patient_care_provider_association
from lib.models.patient import Patient as PatientModel
from lib.models.patient_smbg import PatientSMBG as PatientSMBGModel
from lib.dependencies.database import get_async_postgres_session
from lib.utils.http_exceptions import raise_http_exception


class SMBGMetricsService:
    async def get_active_patients(
        self,
        health_facility_id: Optional[str] = None,
        care_provider_id: Optional[str] = None,
        is_facility_admin: bool = False,
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
                    )
                    .group_by(PatientModel.patient_id)
                    .options(selectinload(PatientModel.smbgs))
                )

                stmt = self._apply_patient_scope_filters(
                    stmt,
                    health_facility_id=health_facility_id,
                    care_provider_id=care_provider_id,
                    is_facility_admin=is_facility_admin,
                )

                result = await session.execute(stmt)
                return list(result.scalars().all())

            except SQLAlchemyError as e:
                raise_http_exception(
                    status_code=500,
                    message="Failed to fetch active SMBG patients",
                    detail=str(e),
                )

    def _apply_patient_scope_filters(
        stmt,
        *,
        health_facility_id: Optional[str] = None,
        care_provider_id: Optional[str] = None,
        is_facility_admin: bool = False,
    ):
        if health_facility_id and is_facility_admin:
            return stmt.where(
                PatientModel.health_facility_id == health_facility_id
            )
        elif care_provider_id:
            return stmt.join(
                patient_care_provider_association,
                PatientModel.patient_id
                == patient_care_provider_association.c.patient_id,
            ).where(
                patient_care_provider_association.c.care_provider_id
                == care_provider_id
            )
        return stmt
