from datetime import datetime, timedelta

from sqlalchemy import select
from lib.core.postgres_store import PostgresStore
from lib.models.patient_connected_app import (
    PatientConnectedApp,
    PatientLibreView,
)
from lib.services.patient_connected_app_service import (
    PatientConnectedAppService,
)
from lib.workers.arq.redis import is_job_in_queue
from lib.workers.tasks.libreview.enqueue import enqueue_libreview_sync_async
from lib.utils.http_exceptions import raise_http_exception
from fastapi import status
from lib.utils.postgres_session_decorator import with_postgres_session
from lib.models.patient import Patient as PatientModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload


class LibreViewService:
    SYNC_INTERVAL_SECONDS = 3 * 60 * 60  # 3 hours

    def __init__(
        self,
        postgres_store: PostgresStore,
        patient_connected_app_service: PatientConnectedAppService,
    ):
        self.postgres_store = postgres_store
        self.patient_connected_app_service = patient_connected_app_service

    async def sync_libreview(self, patient_id: str, force: bool = False) -> dict:
        connected_apps = (
            await self.patient_connected_app_service.get_connected_apps_for_patient(
                patient_id=patient_id,
            )  # type: ignore
        )  # type: ignore

        if not connected_apps.libreview:
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="LibreView not connected for this patient.",
            )

        last_sync = connected_apps.libreview.last_sync_timestamp

        if (
            last_sync
            and not force
            and (datetime.utcnow() - last_sync)
            < timedelta(seconds=self.SYNC_INTERVAL_SECONDS)
        ):
            raise_http_exception(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                message="Sync allowed only once every 3 hours.",
            )

        if not force:
            job_id = f"libreview:sync:{patient_id}"
            if await is_job_in_queue(job_id):
                return {
                    "status": "in_queue",
                    "message": "Sync already queued. Please check back shortly.",
                    "data": {"job_id": job_id},
                }

        job_id = await enqueue_libreview_sync_async(patient_id)
        if not job_id:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Failed to enqueue LibreView sync job.",
            )

        return {
            "message": "Sync request accepted and added to queue.",
            "data": {
                "status": "queued",
                "job_id": job_id,
            },
        }

    @with_postgres_session
    async def get_patients_with_libreview(
        self, *, postgres_session: AsyncSession
    ) -> list[PatientModel]:
        stmt = (
            select(PatientModel)
            .options(
                selectinload(PatientModel.connected_apps).selectinload(
                    PatientConnectedApp.libreview
                )
            )
            .join(PatientModel.connected_apps)
            .join(PatientConnectedApp.libreview)
            .where(PatientLibreView.libreview_id.isnot(None))
        )
        result = await postgres_session.execute(stmt)
        return list(result.scalars().all())
