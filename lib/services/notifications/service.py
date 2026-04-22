"""Service for the patient notification inbox."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional, Tuple
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from lib.core.postgres_store import PostgresStore
from lib.core.types import NotificationCategoryLiteral
from lib.models.gamification import DailyTask
from lib.models.patient_notification import PatientNotification
from lib.schemas.gamification import TaskStatus
from lib.utils.postgres_session_decorator import with_postgres_session

logger = logging.getLogger(__name__)


class PatientNotificationService:
    def __init__(self, postgres_store: PostgresStore):
        self.postgres_store = postgres_store

    @with_postgres_session
    async def list_for_patient(
        self,
        patient_id: str,
        *,
        unread_only: bool = False,
        category: Optional[NotificationCategoryLiteral] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        limit: int = 20,
        offset: int = 0,
        postgres_session: AsyncSession,
    ) -> Tuple[list[PatientNotification], int, int]:
        """Return (rows, total, unread_count) for the patient's inbox."""
        pid = UUID(patient_id)

        base = select(PatientNotification).where(
            PatientNotification.patient_id == pid,
            PatientNotification.dismissed_at.is_(None),
        )
        if unread_only:
            base = base.where(PatientNotification.read_at.is_(None))
        if category:
            base = base.where(PatientNotification.category == category)
        if from_date is not None:
            base = base.where(
                PatientNotification.created_at >= from_date.replace(tzinfo=None)
            )
        if to_date is not None:
            base = base.where(
                PatientNotification.created_at <= to_date.replace(tzinfo=None)
            )

        total = (
            await postgres_session.execute(
                select(func.count()).select_from(base.subquery())
            )
        ).scalar_one()

        unread_count = (
            await postgres_session.execute(
                select(func.count(PatientNotification.id)).where(
                    PatientNotification.patient_id == pid,
                    PatientNotification.read_at.is_(None),
                    PatientNotification.dismissed_at.is_(None),
                )
            )
        ).scalar_one()

        rows = (
            (
                await postgres_session.execute(
                    base.order_by(
                        PatientNotification.created_at.desc(),
                        PatientNotification.id.desc(),
                    )
                    .limit(limit)
                    .offset(offset)
                )
            )
            .scalars()
            .all()
        )

        return list(rows), int(total), int(unread_count)

    @with_postgres_session
    async def resolve_dose_statuses(
        self,
        notifications: list[PatientNotification],
        *,
        postgres_session: AsyncSession,
    ) -> dict[str, str]:
        """Given dose-category rows, return {notification_id: status}.

        Status is derived from the linked DailyTask:
          - completed → 'taken'
          - pending & slot > 2h ago → 'missed'
          - pending otherwise → 'pending'
        """
        task_id_to_notif: dict[str, str] = {}
        for n in notifications:
            if n.category != "medication_dose":
                continue
            tid = (n.data or {}).get("daily_task_id")
            if tid:
                task_id_to_notif[str(tid)] = str(n.id)

        if not task_id_to_notif:
            return {}

        result = await postgres_session.execute(
            select(DailyTask.task_id, DailyTask.status, DailyTask.task_date).where(
                DailyTask.task_id.in_([UUID(t) for t in task_id_to_notif.keys()])
            )
        )

        out: dict[str, str] = {}
        now = datetime.now().replace(tzinfo=None)
        for task_id, status, _task_date in result.all():
            notif_id = task_id_to_notif[str(task_id)]
            if status == TaskStatus.COMPLETED.value:
                out[notif_id] = "taken"
            elif status == TaskStatus.PENDING.value:
                # We don't know the exact slot hour here without joining
                # more context; use a simple heuristic: if the notification
                # was sent > 2h ago and still pending, call it missed.
                out[notif_id] = "pending"
            else:
                out[notif_id] = status
        # Apply "missed" heuristic using created_at (the row's send time).
        for n in notifications:
            nid = str(n.id)
            if out.get(nid) == "pending" and n.created_at:
                if (now - n.created_at).total_seconds() > 2 * 3600:
                    out[nid] = "missed"
        return out

    @with_postgres_session
    async def mark_read(
        self,
        patient_id: str,
        notification_id: str,
        *,
        postgres_session: AsyncSession,
    ) -> int:
        now = datetime.now().replace(tzinfo=None)
        result = await postgres_session.execute(
            update(PatientNotification)
            .where(
                PatientNotification.id == UUID(notification_id),
                PatientNotification.patient_id == UUID(patient_id),
                PatientNotification.read_at.is_(None),
            )
            .values(read_at=now)
        )
        await postgres_session.commit()
        return int(result.rowcount or 0)

    @with_postgres_session
    async def mark_all_read(
        self,
        patient_id: str,
        *,
        postgres_session: AsyncSession,
    ) -> int:
        now = datetime.now().replace(tzinfo=None)
        result = await postgres_session.execute(
            update(PatientNotification)
            .where(
                PatientNotification.patient_id == UUID(patient_id),
                PatientNotification.read_at.is_(None),
            )
            .values(read_at=now)
        )
        await postgres_session.commit()
        return int(result.rowcount or 0)
