from datetime import datetime
from typing import List

from fastapi import status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from lib.core.postgres_store import PostgresStore
from lib.models.patient_vital import PatientVital as PatientVitalModel
from lib.schemas.patient_vital import PatientVitalCreate
from lib.services.patient_profile_service import PatientProfileService
from lib.services.patient_summary.enum import StaleReason
from lib.services.patient_summary.service import PatientSummaryService
from lib.utils.http_exceptions import raise_http_exception
from lib.utils.patient_summary_stale import mark_summary_stale_and_enqueue
from lib.utils.postgres_session_decorator import with_postgres_session
from lib.workers.tasks.vitals.enqueue import enqueue_generate_vital_vector_sync


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

    @with_postgres_session
    async def get_patient_vitals(
        self,
        patient_id: str,
        *,
        limit: int = 20,
        offset: int = 0,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        postgres_session: AsyncSession,
    ) -> tuple[List[PatientVitalModel], int]:
        """Return vitals newest-first with pagination and optional date filter.

        Returns (records, total_count) so the caller can build pagination metadata.
        """
        try:
            from sqlalchemy import func

            base = select(PatientVitalModel).where(
                PatientVitalModel.patient_id == patient_id
            )
            if start_date:
                base = base.where(PatientVitalModel.test_time >= start_date)
            if end_date:
                base = base.where(PatientVitalModel.test_time <= end_date)

            # Total count (before pagination)
            count_result = await postgres_session.execute(
                select(func.count()).select_from(base.subquery())
            )
            total = count_result.scalar() or 0

            # Paginated results
            result = await postgres_session.execute(
                base.order_by(PatientVitalModel.test_time.desc())
                .limit(limit)
                .offset(offset)
            )
            return list(result.scalars().all()), total
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
        postgres_session: AsyncSession,
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

            # Mark affected summaries as stale and enqueue regeneration
            await mark_summary_stale_and_enqueue(
                patient_id=patient_id,
                target_date=vital_data.test_time.date(),
                stale_reason=StaleReason.DATA_UPDATED,
            )

            # Enqueue vital vector generation
            vital_data_dict = {
                "a1c": new_vital.a1c,
                "creatinine": new_vital.creatinine,
                "diastolic_bp": new_vital.diastolic_bp,
                "systolic_bp": new_vital.systolic_bp,
                "heart_rate": new_vital.heart_rate,
                "ketones": new_vital.ketones,
                "respiratory_rate": new_vital.respiratory_rate,
                "spo2": new_vital.spo2,
                "temperature": new_vital.temperature,
                "weight": new_vital.weight,
                "test_time": new_vital.test_time,
                "source_name": new_vital.source_name or "",
                "source_platform": new_vital.source_platform or "",
                "uploaded_at": new_vital.uploaded_at,
            }

            enqueue_generate_vital_vector_sync(
                patient_id=patient_id,
                vital_id=str(new_vital.id),
                vital_data=vital_data_dict,
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

            # Mark affected summaries as stale and enqueue regeneration
            await mark_summary_stale_and_enqueue(
                patient_id=patient_id,
                target_date=test_time.date(),
                stale_reason=StaleReason.DATA_DELETED,
            )
        except SQLAlchemyError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )
