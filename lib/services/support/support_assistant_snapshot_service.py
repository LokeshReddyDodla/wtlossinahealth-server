"""Assemble the read-only patient snapshot the support assistant cites.

Every section is loaded independently and failures are recorded by name in
``SupportSnapshot.lookup_errors`` instead of raised: a broken lookup must
degrade the bot to "I couldn't check that", never block the reply.

Queries run sequentially on one async session — async SQLAlchemy sessions
are single-stream and concurrent ``execute`` calls trip
``IllegalStateChangeError``.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from lib.ai_foundation.agents.support_assistant.contracts import (
    AppDevice,
    CareTeamContact,
    DeviceSyncState,
    FacilityContact,
    PermissionState,
    RecentDocument,
    SupportSnapshot,
)
from lib.core.constants import CareProviderStatus
from lib.core.mongo_store import get_mongo_store
from lib.core.postgres_store import PostgresStore
from lib.core.types import DEFAULT_AI_LANGUAGE
from lib.models.patient import Patient
from lib.models.patient_connected_app import PatientConnectedApp
from lib.models.patient_meal import PatientMeal
from lib.models.patient_package_assignment import (
    AssignmentStatus,
    PatientPackageAssignment,
)
from lib.models.patient_permission import PatientPermission
from lib.models.user_device import UserDevice
from lib.utils.postgres_session_decorator import with_postgres_session

_RECENT_DOCUMENTS = 5
_MEAL_WINDOW_DAYS = 7


class SupportAssistantSnapshotService:
    def __init__(self, postgres_store: Optional[PostgresStore] = None):
        self.postgres_store = postgres_store or PostgresStore()

    @with_postgres_session
    async def build(
        self, patient_id: str, *, postgres_session: AsyncSession
    ) -> SupportSnapshot:
        snapshot = SupportSnapshot()

        await self._load_patient(patient_id, postgres_session, snapshot)
        await self._load_permissions(patient_id, postgres_session, snapshot)
        await self._load_glucose_sources(patient_id, postgres_session, snapshot)
        await self._load_meals(patient_id, postgres_session, snapshot)
        await self._load_device(patient_id, postgres_session, snapshot)
        await self._load_documents(patient_id, snapshot)
        return snapshot

    # -- sections -------------------------------------------------------------

    async def _load_patient(
        self, patient_id: str, session: AsyncSession, snapshot: SupportSnapshot
    ) -> None:
        try:
            result = await session.execute(
                select(Patient)
                .where(Patient.patient_id == patient_id)
                .options(
                    selectinload(Patient.care_providers),
                    selectinload(Patient.health_facility),
                    selectinload(Patient.package_assignments).selectinload(
                        PatientPackageAssignment.package
                    ),
                )
            )
            patient = result.scalars().first()
            if patient is None:
                snapshot.lookup_errors.append("care_team")
                return

            snapshot.patient_first_name = patient.first_name
            snapshot.timezone = patient.timezone
            snapshot.language = patient.preferred_ai_language or DEFAULT_AI_LANGUAGE

            snapshot.care_team = [
                CareTeamContact(
                    name=" ".join(
                        p for p in (cp.first_name, cp.last_name) if p
                    ) or "Care provider",
                    role=cp.role,
                    phone=cp.phone_number,
                    email=cp.email,
                    is_active=cp.status in (None, CareProviderStatus.ACTIVE),
                )
                for cp in (patient.care_providers or [])
            ]

            facility = patient.health_facility
            if facility is not None:
                snapshot.facility = FacilityContact(
                    name=facility.name,
                    phone=facility.phone_number,
                    emergency_phone=facility.emergency_phone_number,
                    operating_hours=facility.operating_hours,
                )

            for assignment in patient.package_assignments or []:
                if assignment.status == AssignmentStatus.ACTIVE and assignment.package:
                    snapshot.active_package_name = assignment.package.name
                    break
        except Exception as exc:
            logger.warning(f"support snapshot: care_team lookup failed for {patient_id}: {exc}")
            snapshot.lookup_errors.append("care_team")

    async def _load_permissions(
        self, patient_id: str, session: AsyncSession, snapshot: SupportSnapshot
    ) -> None:
        try:
            row = (
                await session.execute(
                    select(PatientPermission).where(
                        PatientPermission.patient_id == patient_id
                    )
                )
            ).scalars().first()
            if row is None:
                snapshot.permissions = None
                return
            snapshot.permissions = PermissionState(
                notifications=row.notification_permission,
                health=row.health_permission,
                camera=row.camera_permission,
                gallery=row.gallery_permission,
                storage=row.storage_permission,
                synced_at=row.last_sync_time,
            )
        except Exception as exc:
            logger.warning(f"support snapshot: permissions lookup failed for {patient_id}: {exc}")
            snapshot.lookup_errors.append("permissions")

    async def _load_glucose_sources(
        self, patient_id: str, session: AsyncSession, snapshot: SupportSnapshot
    ) -> None:
        try:
            row = (
                await session.execute(
                    select(PatientConnectedApp)
                    .where(PatientConnectedApp.patient_id == patient_id)
                    .options(
                        selectinload(PatientConnectedApp.libreview),
                        selectinload(PatientConnectedApp.sinocare),
                    )
                )
            ).scalars().first()
            if row is None:
                return
            if row.libreview is not None:
                lv = row.libreview
                snapshot.glucose_sources.append(
                    DeviceSyncState(
                        provider="LibreView (FreeStyle Libre)",
                        sync_status=lv.sync_status,
                        last_sync_at=lv.last_sync_timestamp,
                        last_reading_at=lv.last_cgm_reading_at,
                        live_polling_enabled=lv.llu_enabled,
                        live_last_sync_at=lv.llu_last_sync_timestamp,
                    )
                )
            if row.sinocare is not None:
                sc = row.sinocare
                snapshot.glucose_sources.append(
                    DeviceSyncState(
                        provider="Sinocare",
                        sync_status=sc.sync_status,
                        last_sync_at=sc.last_sync_timestamp,
                        last_reading_at=sc.last_cgm_reading_at,
                    )
                )
        except Exception as exc:
            logger.warning(f"support snapshot: glucose lookup failed for {patient_id}: {exc}")
            snapshot.lookup_errors.append("glucose_sources")

    async def _load_meals(
        self, patient_id: str, session: AsyncSession, snapshot: SupportSnapshot
    ) -> None:
        try:
            since = date.today() - timedelta(days=_MEAL_WINDOW_DAYS)
            row = (
                await session.execute(
                    select(
                        func.max(PatientMeal.date),
                        func.count(PatientMeal.id).filter(PatientMeal.date >= since),
                    ).where(PatientMeal.patient_id == patient_id)
                )
            ).one()
            last_date, recent_count = row[0], row[1]
            snapshot.last_meal_date = last_date.isoformat() if last_date else None
            snapshot.meals_last_7_days = int(recent_count or 0)
        except Exception as exc:
            logger.warning(f"support snapshot: meals lookup failed for {patient_id}: {exc}")
            snapshot.lookup_errors.append("meals")

    async def _load_device(
        self, patient_id: str, session: AsyncSession, snapshot: SupportSnapshot
    ) -> None:
        try:
            row = (
                await session.execute(
                    select(UserDevice)
                    .where(
                        UserDevice.user_id == patient_id,
                        UserDevice.is_active.is_(True),
                    )
                    .order_by(
                        UserDevice.last_active_at.desc().nulls_last(),
                        UserDevice.last_updated_at.desc(),
                    )
                    .limit(1)
                )
            ).scalars().first()
            if row is None:
                snapshot.device = None
                return
            snapshot.device = AppDevice(
                platform=row.device_type,
                os_version=row.platform_version,
                app_version=row.app_version,
                model=" ".join(p for p in (row.manufacturer, row.device_model) if p) or None,
                last_active_at=row.last_active_at,
            )
        except Exception as exc:
            logger.warning(f"support snapshot: device lookup failed for {patient_id}: {exc}")
            snapshot.lookup_errors.append("device")

    async def _load_documents(self, patient_id: str, snapshot: SupportSnapshot) -> None:
        try:
            cursor = (
                get_mongo_store()
                .db["patient_documents"]
                .find(
                    {"patient_id": patient_id},
                    {"file.name": 1, "category": 1, "metadata.created_at": 1},
                )
                .sort("metadata.created_at", -1)
                .limit(_RECENT_DOCUMENTS)
            )
            docs = await cursor.to_list(length=_RECENT_DOCUMENTS)
            snapshot.recent_documents = [
                RecentDocument(
                    file_name=(d.get("file") or {}).get("name"),
                    category=d.get("category"),
                    uploaded_at=_as_datetime((d.get("metadata") or {}).get("created_at")),
                )
                for d in docs
            ]
        except Exception as exc:
            logger.warning(f"support snapshot: documents lookup failed for {patient_id}: {exc}")
            snapshot.lookup_errors.append("documents")


def _as_datetime(value) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None
