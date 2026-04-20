"""Tests for PatientNotificationService — focused on dose-status derivation."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest


def _fake_notif(category, data=None, sent_at=None):
    return SimpleNamespace(
        id=uuid4(),
        category=category,
        data=data or {},
        sent_at=sent_at,
    )


def _fake_session_with_tasks(task_rows):
    session = MagicMock()
    result = MagicMock()
    result.all = MagicMock(return_value=task_rows)
    session.execute = AsyncMock(return_value=result)
    return session


@pytest.mark.asyncio
async def test_dose_completed_becomes_taken():
    from lib.schemas.gamification import TaskStatus
    from lib.services.notifications.service import PatientNotificationService

    tid = uuid4()
    notif = _fake_notif(
        "medication_dose",
        data={"daily_task_id": str(tid)},
        sent_at=datetime.now() - timedelta(hours=1),
    )
    session = _fake_session_with_tasks(
        [(tid, TaskStatus.COMPLETED.value, None)],
    )

    svc = PatientNotificationService(postgres_store=MagicMock())
    out = await PatientNotificationService.resolve_dose_statuses.__wrapped__(
        svc, [notif], postgres_session=session
    )

    assert out[str(notif.id)] == "taken"


@pytest.mark.asyncio
async def test_dose_pending_over_2h_becomes_missed():
    from lib.schemas.gamification import TaskStatus
    from lib.services.notifications.service import PatientNotificationService

    tid = uuid4()
    notif = _fake_notif(
        "medication_dose",
        data={"daily_task_id": str(tid)},
        sent_at=datetime.now() - timedelta(hours=3),
    )
    session = _fake_session_with_tasks(
        [(tid, TaskStatus.PENDING.value, None)],
    )

    svc = PatientNotificationService(postgres_store=MagicMock())
    out = await PatientNotificationService.resolve_dose_statuses.__wrapped__(
        svc, [notif], postgres_session=session
    )

    assert out[str(notif.id)] == "missed"


@pytest.mark.asyncio
async def test_dose_pending_recent_stays_pending():
    from lib.schemas.gamification import TaskStatus
    from lib.services.notifications.service import PatientNotificationService

    tid = uuid4()
    notif = _fake_notif(
        "medication_dose",
        data={"daily_task_id": str(tid)},
        sent_at=datetime.now() - timedelta(minutes=30),
    )
    session = _fake_session_with_tasks(
        [(tid, TaskStatus.PENDING.value, None)],
    )

    svc = PatientNotificationService(postgres_store=MagicMock())
    out = await PatientNotificationService.resolve_dose_statuses.__wrapped__(
        svc, [notif], postgres_session=session
    )

    assert out[str(notif.id)] == "pending"


@pytest.mark.asyncio
async def test_non_dose_notifications_skipped():
    """Insights/gamification rows should produce no status entries."""
    from lib.services.notifications.service import PatientNotificationService

    notif = _fake_notif("health_insight")
    session = _fake_session_with_tasks([])

    svc = PatientNotificationService(postgres_store=MagicMock())
    out = await PatientNotificationService.resolve_dose_statuses.__wrapped__(
        svc, [notif], postgres_session=session
    )

    assert out == {}
