from datetime import datetime, timedelta
import json

from sqlalchemy import select, update
from lib.core.cache_store import CacheStore
from lib.core.postgres_store import PostgresStore
from lib.models.patient_connected_app import (
    PatientConnectedApp,
    PatientLibreView,
)
from lib.services.patient_connected_app_service import (
    PatientConnectedAppService,
)
from lib.services.sqs_service import SQSService
from lib.utils.http_exceptions import raise_http_exception
from fastapi import Depends, HTTPException, Query, Request, status
from lib.schemas.patient_connected_app import (
    PatientLibreView as PatientLibreViewSchema,
)
from lib.utils.postgres_session_decorator import with_postgres_session
from lib.models.patient import Patient as PatientModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload


class LibreViewService:
    SYNC_INTERVAL_SECONDS = 2 * 60 * 60  # 2 hours
    REDIS_SYNC_TTL_SECONDS = 30 * 60  # Optional: Keep Redis lock for 30 min

    def __init__(
        self,
        postgres_store: PostgresStore,
        patient_connected_app_service: PatientConnectedAppService,
        libreview_sync_queue: SQSService,
        libreview_sync_store: CacheStore,
    ):
        self.postgres_store = postgres_store
        self.patient_connected_app_service = patient_connected_app_service
        self.libreview_sync_queue = libreview_sync_queue
        self.libreview_sync_store = libreview_sync_store

    async def sync_libreview(self, patient_id: str, user_id: str) -> dict:
        connected_apps = (
            await self.patient_connected_app_service.get_connected_apps_for_patient(
                patient_id=patient_id,
            )
        )  # type: ignore

        if not connected_apps.libreview:
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="LibreView not connected for this patient.",
            )

        libreview = PatientLibreViewSchema.model_validate(connected_apps.libreview)
        last_sync = connected_apps.libreview.last_sync_timestamp

        if last_sync and (datetime.utcnow() - last_sync) < timedelta(
            seconds=self.SYNC_INTERVAL_SECONDS
        ):
            raise_http_exception(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                message="Sync allowed only once every 2 hours.",
            )

        redis_key = f"{libreview.libreview_id}:{patient_id}"
        sqs_deduplication_id = f"{libreview.libreview_id}-{patient_id}"

        payload = {
            "patient_id": patient_id,
            "libreview_id": libreview.libreview_id,
            "requested_by": str(user_id),
            "timestamp": int(datetime.utcnow().timestamp() * 1000),
        }

        lock_acquired = self.libreview_sync_store.set_key(
            redis_key,
            json.dumps(payload),
            expire=self.REDIS_SYNC_TTL_SECONDS,
            nx=True,  # SET only if key does NOT exist
        )

        if not lock_acquired:
            return {
                "message": "Sync already in progress (in queue).",
                "data": {
                    "status": "already_queued",
                    "last_sync_timestamp": last_sync.isoformat() if last_sync else None,
                },
            }

        self.libreview_sync_queue.send_message(
            deduplication_id=sqs_deduplication_id,
            payload=payload,
        )

        # Update last_sync_timestamp when sync is queued
        await self._update_last_sync_timestamp(patient_id)

        # Get updated timestamp for response
        updated_connected_apps = (
            await self.patient_connected_app_service.get_connected_apps_for_patient(
                patient_id=patient_id,
            )
        )
        updated_last_sync = (
            updated_connected_apps.libreview.last_sync_timestamp
            if updated_connected_apps.libreview
            else None
        )

        return {
            "message": "Sync request accepted and added to queue.",
            "data": {
                "status": "queued",
                "last_sync_timestamp": updated_last_sync.isoformat()
                if updated_last_sync
                else None,
            },
        }

    @with_postgres_session
    async def _update_last_sync_timestamp(
        self, patient_id: str, *, postgres_session: AsyncSession
    ):
        connected_app_id = await postgres_session.scalar(
            select(PatientConnectedApp.id).where(
                PatientConnectedApp.patient_id == patient_id
            )
        )

        if not connected_app_id:
            return

        await postgres_session.execute(
            update(PatientLibreView)
            .where(PatientLibreView.connected_app_id == connected_app_id)
            .values(last_sync_timestamp=datetime.utcnow())
        )

        await postgres_session.commit()

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
