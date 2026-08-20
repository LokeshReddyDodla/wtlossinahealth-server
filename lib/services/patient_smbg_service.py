import logging
from datetime import datetime
from typing import List, Tuple

from fastapi import status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from lib.core.postgres_store import PostgresStore
from lib.models.patient_smbg import PatientSMBG as PatientSMBGModel
from lib.schemas.patient_smbg import PatientSMBGCreate
from lib.services.patient_profile_service import PatientProfileService
from lib.services.vector import SMBGVectorService
from lib.utils.http_exceptions import raise_http_exception
from lib.utils.postgres_session_decorator import with_postgres_session

from lib.workers.tasks.smbg.enqueue import (
    enqueue_generate_smbg_vector_async,
)

logger = logging.getLogger(__name__)


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

    @with_postgres_session
    async def get_patient_smbgs(
        self,
        patient_id: str,
        *,
        since: datetime | None = None,
        limit: int | None = None,
        postgres_session: AsyncSession,
    ) -> List[PatientSMBGModel]:
        try:
            stmt = (
                select(PatientSMBGModel)
                .where(PatientSMBGModel.patient_id == patient_id)
                .order_by(PatientSMBGModel.reading_time.desc())
            )
            if since is not None:
                stmt = stmt.where(PatientSMBGModel.reading_time >= since)
            if limit is not None:
                stmt = stmt.limit(limit)
            result = await postgres_session.execute(stmt)
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
            await enqueue_generate_smbg_vector_async(
                patient_id=patient_id,
                reading_id=str(new_smbg.id),
                reading_data=reading_data,
            )

            return new_smbg

        except SQLAlchemyError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    @with_postgres_session
    async def update_smbg(
        self,
        smbg_id: str,
        patient_id: str,
        update_data: PatientSMBGCreate,
        *,
        postgres_session: AsyncSession,
    ) -> PatientSMBGModel:
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

            smbg_record.glucose_level = update_data.glucose_level
            smbg_record.reading_time = update_data.reading_time
            smbg_record.source_name = update_data.source_name
            smbg_record.source_platform = update_data.source_platform
            smbg_record.type = update_data.type
            smbg_record.notes = update_data.notes

            await postgres_session.commit()
            await postgres_session.refresh(smbg_record)

            reading_data = {
                "glucose_mgdl": smbg_record.glucose_level,
                "reading_time": smbg_record.reading_time.isoformat(),
                "type": smbg_record.type,
                "notes": smbg_record.notes,
                "uploaded_at": smbg_record.uploaded_at,
                "source": smbg_record.source_name or "app",
            }
            await enqueue_generate_smbg_vector_async(
                patient_id=patient_id,
                reading_id=str(smbg_record.id),
                reading_data=reading_data,
            )

            try:
                from lib.core.container import container
                from lib.ai_foundation.agents.proactive_monitor.insight_tracker import InsightTracker
                tracker = container.resolve(InsightTracker)
                await tracker.delete_by_entity("smbg", smbg_id)
            except Exception:
                pass

            return smbg_record

        except SQLAlchemyError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

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

            try:
                await self.smbg_vector_service.delete_smbg_vector(smbg_id)
            except Exception:
                logger.exception("Inline vector delete failed for SMBG %s — enqueuing retry", smbg_id)
                from lib.workers.arq.redis import enqueue_job

                await enqueue_job(
                    "delete_smbg_vector_task", smbg_id,
                    _job_id=f"smbg:vector:delete:{smbg_id}",
                )

            try:
                from lib.core.container import container
                from lib.ai_foundation.agents.proactive_monitor.insight_tracker import InsightTracker
                tracker = container.resolve(InsightTracker)
                await tracker.delete_by_entity("smbg", smbg_id)
            except Exception:
                pass
        except SQLAlchemyError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )
