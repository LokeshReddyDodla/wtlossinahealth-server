"""SupportAssistantSnapshotService — PG/Mongo rows -> SupportSnapshot.

Fake session dispatches on the table named in the compiled statement, the
same trick the profile-resolver tests use. Also checks that one failing
section is recorded in ``lookup_errors`` without losing the others.
"""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import lib.models  # noqa: F401
from lib.core.constants import CareProviderStatus
from lib.models.patient import Patient  # noqa: F401
from lib.models.patient_package_assignment import AssignmentStatus
from lib.services.support import support_assistant_snapshot_service as module
from lib.services.support.support_assistant_snapshot_service import (
    SupportAssistantSnapshotService,
)

PID = "11111111-1111-4111-8111-111111111111"


def _patient_row():
    return SimpleNamespace(
        first_name="Asha",
        timezone="Asia/Kolkata",
        preferred_ai_language="hi",
        care_providers=[
            SimpleNamespace(
                first_name="Ravi", last_name="Rao", role="Doctor", phone_number="+912222",
                email="rao@x.in", status=CareProviderStatus.ACTIVE,
            ),
            SimpleNamespace(
                first_name="Priya", last_name=None, role="Dietitian", phone_number=None,
                email="p@x.in", status=CareProviderStatus.ON_LEAVE,
            ),
        ],
        health_facility=SimpleNamespace(
            name="Sunrise Clinic", phone_number="+911111", emergency_phone_number="+919999",
            operating_hours="9-6",
        ),
        package_assignments=[
            SimpleNamespace(status=AssignmentStatus.EXPIRED, package=SimpleNamespace(name="Old")),
            SimpleNamespace(status=AssignmentStatus.ACTIVE, package=SimpleNamespace(name="Diabetes Care 90")),
        ],
    )


def _session(*, patients=None, permissions=None, connected=None, meals=None, devices=None, fail_tables=()):
    """Return a session whose ``execute`` answers per table. ``meals`` is
    the (max_date, count) row; everything else is a scalars().first()."""

    async def execute(stmt):
        compiled = str(stmt.compile()).lower()
        for name in fail_tables:
            if name in compiled:
                raise RuntimeError(f"{name} unavailable")
        result = MagicMock()
        if "patient_meals" in compiled:
            result.one = MagicMock(return_value=meals or (None, 0))
            return result
        if "patient_permissions" in compiled:
            first = permissions
        elif "patient_connected_apps" in compiled:
            first = connected
        elif "user_devices" in compiled:
            first = devices
        elif "patients" in compiled:
            first = patients
        else:
            first = None
        scalars = MagicMock()
        scalars.first = MagicMock(return_value=first)
        result.scalars = MagicMock(return_value=scalars)
        return result

    session = MagicMock()
    session.execute = AsyncMock(side_effect=execute)
    return session


def _mongo(docs=None, *, fail=False):
    cursor = MagicMock()
    cursor.sort = MagicMock(return_value=cursor)
    cursor.limit = MagicMock(return_value=cursor)
    if fail:
        cursor.to_list = AsyncMock(side_effect=RuntimeError("mongo down"))
    else:
        cursor.to_list = AsyncMock(return_value=docs or [])
    collection = MagicMock()
    collection.find = MagicMock(return_value=cursor)
    store = MagicMock()
    store.db = {"patient_documents": collection}
    return store


async def _build(session, mongo, monkeypatch):
    monkeypatch.setattr(module, "get_mongo_store", lambda: mongo)
    svc = SupportAssistantSnapshotService(postgres_store=MagicMock())
    return await svc.build.__wrapped__(svc, PID, postgres_session=session)


@pytest.mark.asyncio
async def test_full_snapshot_mapping(monkeypatch):
    session = _session(
        patients=_patient_row(),
        permissions=SimpleNamespace(
            notification_permission=True, health_permission=False, camera_permission=False,
            gallery_permission=True, storage_permission=True, last_sync_time=datetime(2026, 9, 9, 10),
        ),
        connected=SimpleNamespace(
            libreview=SimpleNamespace(
                sync_status="paused", last_sync_timestamp=datetime(2026, 9, 8, 17),
                last_cgm_reading_at=datetime(2026, 9, 8, 16, 50), llu_enabled=True,
                llu_last_sync_timestamp=None,
            ),
            sinocare=None,
        ),
        meals=(date(2026, 9, 8), 4),
        devices=SimpleNamespace(
            device_type="Android", platform_version="14", app_version="2.3.1",
            manufacturer="Samsung", device_model="SM-A546", last_active_at=datetime(2026, 9, 9, 8),
        ),
    )
    mongo = _mongo([
        {"file": {"name": "hba1c.pdf"}, "category": "report", "metadata": {"created_at": datetime(2026, 9, 7)}},
        {"file": {"name": "x.jpg"}, "category": "other", "metadata": {"created_at": "2026-09-06T10:00:00"}},
    ])

    snap = await _build(session, mongo, monkeypatch)

    assert snap.lookup_errors == []
    assert snap.patient_first_name == "Asha"
    assert snap.timezone == "Asia/Kolkata"
    assert snap.language == "hi"

    assert [c.name for c in snap.care_team] == ["Ravi Rao", "Priya"]
    assert snap.care_team[0].phone == "+912222" and snap.care_team[0].is_active is True
    assert snap.care_team[1].is_active is False
    assert snap.facility.emergency_phone == "+919999"
    assert snap.active_package_name == "Diabetes Care 90"

    assert snap.permissions.camera is False and snap.permissions.gallery is True

    assert len(snap.glucose_sources) == 1
    src = snap.glucose_sources[0]
    assert src.provider.startswith("LibreView") and src.sync_status == "paused"
    assert src.live_polling_enabled is True

    assert snap.last_meal_date == "2026-09-08" and snap.meals_last_7_days == 4

    assert snap.device.platform == "Android" and snap.device.model == "Samsung SM-A546"
    assert snap.device.app_version == "2.3.1"

    assert [d.file_name for d in snap.recent_documents] == ["hba1c.pdf", "x.jpg"]
    assert snap.recent_documents[1].uploaded_at == datetime(2026, 9, 6, 10)
    mongo.db["patient_documents"].find.assert_called_once()
    assert mongo.db["patient_documents"].find.call_args.args[0] == {"patient_id": PID}


@pytest.mark.asyncio
async def test_missing_rows_are_not_errors(monkeypatch):
    session = _session(patients=None)
    snap = await _build(session, _mongo(), monkeypatch)

    # Unknown patient: care-team section unavailable; the rest simply empty.
    assert snap.lookup_errors == ["care_team"]
    assert snap.permissions is None
    assert snap.glucose_sources == []
    assert snap.meals_last_7_days == 0 and snap.last_meal_date is None
    assert snap.device is None
    assert snap.recent_documents == []


@pytest.mark.asyncio
async def test_one_failing_section_does_not_poison_the_others(monkeypatch):
    session = _session(patients=_patient_row(), meals=(date(2026, 9, 1), 1), fail_tables=("patient_permissions", "user_devices"))
    snap = await _build(session, _mongo(fail=True), monkeypatch)

    assert sorted(snap.lookup_errors) == ["device", "documents", "permissions"]
    assert snap.patient_first_name == "Asha"
    assert snap.last_meal_date == "2026-09-01"
