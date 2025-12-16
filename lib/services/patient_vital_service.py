from datetime import datetime
from typing import List, Optional, Tuple

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from lib.core.postgres_store import PostgresStore
from lib.models.patient_vital import PatientVital as PatientVitalModel
from lib.schemas.patient_vital import PatientVital as PatientVitalSchema
from lib.schemas.patient_vital import PatientVitalCreate
from lib.services.patient_profile_service import PatientProfileService
from lib.services.patient_summary.service import PatientSummaryService
from lib.utils.http_exceptions import raise_http_exception
from lib.utils.postgres_session_decorator import with_postgres_session


class PatientVitalService:
    def __init__(
        self,
        postgres_store: PostgresStore,
        patient_profile_service: PatientProfileService,
        patient_summary_service: PatientSummaryService,
    ):
        self.postgres_store = postgres_store
        self.patient_profile_service = patient_profile_service
        self.patient_summary_service = patient_summary_service

    async def _mark_summaries_stale(
        self, patient_id: str, test_time: datetime
    ) -> None:
        if not self.patient_summary_service:
            return

        try:
            from lib.services.patient_summary.enum import StaleReason

            target_date = test_time.date() if isinstance(test_time, datetime) else test_time

            await self.patient_summary_service.mark_summaries_as_stale(
                patient_id=patient_id,
                target_date=target_date,
                stale_reason=StaleReason.DATA_UPDATED,
            )
        except Exception as e:
            # Don't fail the operation if marking stale fails
            import logging
            logging.warning(
                f"Failed to mark summaries as stale for {patient_id}: {e}"
            )

    @with_postgres_session
    async def get_patient_vitals(
        self, patient_id: str, *, postgres_session: AsyncSession
    ) -> List[PatientVitalModel]:
        try:
            result = await postgres_session.execute(
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

    @with_postgres_session
    async def upload_patient_vital(
        self,
        patient_id: str,
        vital_data: PatientVitalCreate,
        *,
        postgres_session: AsyncSession
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
                source_name=vital_data.source_name,
                source_platform=vital_data.source_platform,
            )

            postgres_session.add(new_vital)
            await postgres_session.commit()
            await postgres_session.refresh(new_vital)

            # Mark affected summaries as stale
            await self._mark_summaries_stale(
                patient_id=patient_id,
                test_time=vital_data.test_time,
            )

            return new_vital

        except SQLAlchemyError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    @with_postgres_session
    async def delete_vital(
        self, vital_id: str, patient_id: str, *, postgres_session: AsyncSession
    ):
        try:
            result = await postgres_session.execute(
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

            # Store test_time before deletion for marking summaries stale
            test_time = vital_record.test_time

            await postgres_session.delete(vital_record)
            await postgres_session.commit()

            # Mark affected summaries as stale
            await self._mark_summaries_stale(
                patient_id=patient_id,
                test_time=test_time,
            )
        except SQLAlchemyError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )
