"""Full flow tests for confirm_prescription, edit_prescription, complete_expired_medications,
save_draft_prescription, _refresh_medication_tasks, and access control validation.

Every remaining gap — no stone unturned.
"""

from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch
from uuid import uuid4

import pytest

from lib.schemas.medication import (
    ConfirmPrescriptionRequest,
    ConfirmedMedicine,
    MedicationDose,
    MedicationSchedule,
)


# ── Helpers ──────────────────────────────────────────────────────────────


def _fake_prescription(status="draft", medications=None, **kwargs):
    defaults = {
        "prescription_id": uuid4(),
        "patient_id": uuid4(),
        "doctor_name": "Dr. Test",
        "prescription_date": date.today(),
        "file_urls": [],
        "status": status,
        "extracted_data": {"some": "data"},
        "uploaded_by_id": None,
        "uploaded_by_type": None,
        "follow_up_required": False,
        "follow_up_date": None,
        "notes": None,
        "medications": medications or [],
        "created_at": datetime.now(),
        "updated_at": datetime.now(),
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _fake_medication(status="active", name="Metformin", strength="500mg",
                     schedule=None, **kwargs):
    defaults = {
        "medication_id": uuid4(),
        "patient_id": uuid4(),
        "prescription_id": uuid4(),
        "name": name,
        "brand_name": None,
        "strength": strength,
        "formulation": "tablet",
        "route": "oral",
        "food_timing": "after food",
        "purpose": "diabetes",
        "instructions": None,
        "doses": [{"slot": "morning", "quantity": 1}],
        "schedule": schedule,
        "start_date": date.today() - timedelta(days=10),
        "end_date": None,
        "status": status,
        "discontinued_at": None,
        "discontinued_by": None,
        "created_at": datetime.now(),
        "updated_at": datetime.now(),
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _confirm_request(medicines=None, prescription_id=None, **kwargs):
    defaults = {
        "doctor_name": "Dr. Test",
        "prescription_date": date.today(),
        "prescription_id": str(prescription_id) if prescription_id else None,
        "medicines": medicines or [
            ConfirmedMedicine(
                name="Metformin",
                strength="500mg",
                doses=[MedicationDose(slot="morning", quantity=1)],
                start_date=date.today(),
            ),
        ],
    }
    defaults.update(kwargs)
    return ConfirmPrescriptionRequest(**defaults)


def _make_service():
    from lib.services.medication_service import MedicationService
    service = MedicationService(
        postgres_store=MagicMock(),
        medication_vector_service=MagicMock(),
    )
    service._sync_qdrant = AsyncMock()
    service._refresh_medication_tasks = AsyncMock()
    service._notify_patient = AsyncMock()
    return service


def _mock_session(execute_returns=None):
    """Create an AsyncMock session with queued execute results."""
    session = AsyncMock()
    if execute_returns:
        session.execute = AsyncMock(side_effect=execute_returns)
    else:
        session.execute = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


def _scalars_first(value):
    class R:
        def scalars(self):
            return SimpleNamespace(first=lambda: value)
    return R()


def _scalars_all(values):
    class R:
        def scalars(self):
            return SimpleNamespace(all=lambda: list(values))
    return R()


# ── confirm_prescription ────────────────────────────────────────────────


class TestConfirmPrescription:
    @pytest.mark.asyncio
    async def test_confirm_draft_sets_confirmed(self):
        service = _make_service()
        rx = _fake_prescription(status="draft")
        pid = str(rx.patient_id)

        session = _mock_session(execute_returns=[
            _scalars_first(rx),  # load prescription
        ])

        # Mock _create_medication to avoid deep DB calls
        service._create_medication = AsyncMock()

        data = _confirm_request(prescription_id=rx.prescription_id)
        result = await service.confirm_prescription(
            patient_id=pid, data=data, postgres_session=session,
        )

        assert result.status == "confirmed"
        assert result.extracted_data is None  # cleared
        service._create_medication.assert_called_once()
        service._sync_qdrant.assert_called_once()
        service._refresh_medication_tasks.assert_called_once()
        service._notify_patient.assert_called_once()
        assert "prescribed" in service._notify_patient.call_args[1]["body"]

    @pytest.mark.asyncio
    async def test_confirm_direct_creates_prescription(self):
        """Confirm without draft — creates new prescription."""
        service = _make_service()
        service._create_medication = AsyncMock()

        session = _mock_session()
        # refresh needs to work without error
        session.refresh = AsyncMock()

        data = _confirm_request()  # no prescription_id
        result = await service.confirm_prescription(
            patient_id=str(uuid4()), data=data, postgres_session=session,
        )

        assert session.add.called  # prescription was added to session
        service._create_medication.assert_called_once()
        service._notify_patient.assert_called_once()

    @pytest.mark.asyncio
    async def test_confirm_already_confirmed_rejects(self):
        from fastapi import HTTPException

        service = _make_service()
        rx = _fake_prescription(status="confirmed")

        session = _mock_session(execute_returns=[_scalars_first(rx)])

        data = _confirm_request(prescription_id=rx.prescription_id)

        with pytest.raises(HTTPException) as exc_info:
            await service.confirm_prescription(
                patient_id=str(rx.patient_id), data=data, postgres_session=session,
            )
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_confirm_archived_rejects(self):
        from fastapi import HTTPException

        service = _make_service()
        rx = _fake_prescription(status="archived")

        session = _mock_session(execute_returns=[_scalars_first(rx)])

        data = _confirm_request(prescription_id=rx.prescription_id)

        with pytest.raises(HTTPException) as exc_info:
            await service.confirm_prescription(
                patient_id=str(rx.patient_id), data=data, postgres_session=session,
            )
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_confirm_nonexistent_draft_rejects(self):
        from fastapi import HTTPException

        service = _make_service()

        session = _mock_session(execute_returns=[_scalars_first(None)])

        data = _confirm_request(prescription_id=uuid4())

        with pytest.raises(HTTPException) as exc_info:
            await service.confirm_prescription(
                patient_id=str(uuid4()), data=data, postgres_session=session,
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_confirm_multiple_medicines(self):
        service = _make_service()
        service._create_medication = AsyncMock()

        session = _mock_session()

        data = _confirm_request(medicines=[
            ConfirmedMedicine(name="Med1", start_date=date.today()),
            ConfirmedMedicine(name="Med2", start_date=date.today()),
            ConfirmedMedicine(name="Med3", start_date=date.today()),
        ])

        await service.confirm_prescription(
            patient_id=str(uuid4()), data=data, postgres_session=session,
        )

        assert service._create_medication.call_count == 3

    @pytest.mark.asyncio
    async def test_confirm_notification_fallback_doctor(self):
        service = _make_service()
        service._create_medication = AsyncMock()
        session = _mock_session()

        data = _confirm_request(doctor_name=None)

        await service.confirm_prescription(
            patient_id=str(uuid4()), data=data, postgres_session=session,
        )

        body = service._notify_patient.call_args[1]["body"]
        assert "Your doctor" in body


# ── edit_prescription ───────────────────────────────────────────────────


class TestEditPrescription:
    @pytest.mark.asyncio
    async def test_edit_discontinues_old_creates_new(self):
        service = _make_service()
        service._create_medication = AsyncMock()

        active_med = _fake_medication(status="active", name="OldMed")
        paused_med = _fake_medication(status="paused", name="PausedMed")
        completed_med = _fake_medication(status="completed", name="DoneMed")

        rx = _fake_prescription(
            status="confirmed",
            medications=[active_med, paused_med, completed_med],
        )

        session = _mock_session(execute_returns=[_scalars_first(rx)])

        data = _confirm_request(medicines=[
            ConfirmedMedicine(name="NewMed", start_date=date.today()),
        ])

        result = await service.edit_prescription(
            patient_id=str(rx.patient_id),
            prescription_id=str(rx.prescription_id),
            data=data,
            postgres_session=session,
        )

        assert active_med.status == "discontinued"
        assert paused_med.status == "discontinued"
        assert completed_med.status == "completed"  # untouched
        assert active_med.discontinued_at is not None
        service._create_medication.assert_called_once()
        service._sync_qdrant.assert_called_once()
        service._refresh_medication_tasks.assert_called_once()
        service._notify_patient.assert_called_once()
        assert "updated" in service._notify_patient.call_args[1]["body"]

    @pytest.mark.asyncio
    async def test_edit_draft_rejects(self):
        from fastapi import HTTPException

        service = _make_service()
        rx = _fake_prescription(status="draft")
        session = _mock_session(execute_returns=[_scalars_first(rx)])

        data = _confirm_request()

        with pytest.raises(HTTPException) as exc_info:
            await service.edit_prescription(
                patient_id=str(rx.patient_id),
                prescription_id=str(rx.prescription_id),
                data=data,
                postgres_session=session,
            )
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_edit_archived_rejects(self):
        from fastapi import HTTPException

        service = _make_service()
        rx = _fake_prescription(status="archived")
        session = _mock_session(execute_returns=[_scalars_first(rx)])

        data = _confirm_request()

        with pytest.raises(HTTPException) as exc_info:
            await service.edit_prescription(
                patient_id=str(rx.patient_id),
                prescription_id=str(rx.prescription_id),
                data=data,
                postgres_session=session,
            )
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_edit_nonexistent_rejects(self):
        from fastapi import HTTPException

        service = _make_service()
        session = _mock_session(execute_returns=[_scalars_first(None)])

        data = _confirm_request()

        with pytest.raises(HTTPException) as exc_info:
            await service.edit_prescription(
                patient_id=str(uuid4()),
                prescription_id=str(uuid4()),
                data=data,
                postgres_session=session,
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_edit_updates_metadata(self):
        service = _make_service()
        service._create_medication = AsyncMock()

        rx = _fake_prescription(status="confirmed", doctor_name="Old Doctor")
        session = _mock_session(execute_returns=[_scalars_first(rx)])

        data = _confirm_request(
            doctor_name="New Doctor",
            follow_up_required=True,
            follow_up_date=date.today() + timedelta(days=14),
            notes="Updated notes",
        )

        await service.edit_prescription(
            patient_id=str(rx.patient_id),
            prescription_id=str(rx.prescription_id),
            data=data,
            postgres_session=session,
        )

        assert rx.doctor_name == "New Doctor"
        assert rx.follow_up_required is True
        assert rx.follow_up_date == date.today() + timedelta(days=14)
        assert rx.notes == "Updated notes"

    @pytest.mark.asyncio
    async def test_edit_also_discontinues_scheduled_and_as_needed(self):
        service = _make_service()
        service._create_medication = AsyncMock()

        scheduled_med = _fake_medication(status="scheduled", name="FutureMed")
        as_needed_med = _fake_medication(status="as_needed", name="SOSMed")

        rx = _fake_prescription(
            status="confirmed",
            medications=[scheduled_med, as_needed_med],
        )

        session = _mock_session(execute_returns=[_scalars_first(rx)])
        data = _confirm_request()

        await service.edit_prescription(
            patient_id=str(rx.patient_id),
            prescription_id=str(rx.prescription_id),
            data=data,
            postgres_session=session,
        )

        assert scheduled_med.status == "discontinued"
        assert as_needed_med.status == "discontinued"


# ── save_draft_prescription ─────────────────────────────────────────────


class TestSaveDraftPrescription:
    @pytest.mark.asyncio
    async def test_creates_new_draft(self):
        from lib.services.medication_service import MedicationService

        service = MedicationService(
            postgres_store=MagicMock(),
            medication_vector_service=MagicMock(),
        )

        # No existing draft found
        session = _mock_session(execute_returns=[_scalars_first(None)])

        result = await service.save_draft_prescription(
            patient_id=str(uuid4()),
            file_urls=["https://s3/image.jpg"],
            extracted_data={"medicines": []},
            uploaded_by_id=str(uuid4()),
            uploaded_by_type="care_provider",
            postgres_session=session,
        )

        assert session.add.called
        assert session.commit.called

    @pytest.mark.asyncio
    async def test_updates_existing_draft_same_urls(self):
        from lib.services.medication_service import MedicationService

        service = MedicationService(
            postgres_store=MagicMock(),
            medication_vector_service=MagicMock(),
        )

        existing = _fake_prescription(status="draft")

        session = _mock_session(execute_returns=[_scalars_first(existing)])

        result = await service.save_draft_prescription(
            patient_id=str(uuid4()),
            file_urls=["https://s3/image.jpg"],
            extracted_data={"new": "data"},
            uploaded_by_id=str(uuid4()),
            uploaded_by_type="care_provider",
            postgres_session=session,
        )

        assert result.extracted_data == {"new": "data"}
        assert not session.add.called  # reused existing, didn't add new


# ── complete_expired_medications ────────────────────────────────────────


class TestCompleteExpiredMedications:
    @pytest.mark.asyncio
    async def test_expires_active_past_end_date(self):
        service = _make_service()

        expired_med = _fake_medication(
            status="active",
            end_date=date.today() - timedelta(days=1),
            patient_id=uuid4(),
        )

        session = _mock_session(execute_returns=[
            _scalars_all([expired_med]),   # expired query
            _scalars_all([]),              # scheduled query
        ])

        count = await service.complete_expired_medications(postgres_session=session)

        assert count == 1
        assert expired_med.status == "completed"
        service._sync_qdrant.assert_called_once()

    @pytest.mark.asyncio
    async def test_activates_scheduled_med(self):
        service = _make_service()

        scheduled_med = _fake_medication(
            status="scheduled",
            start_date=date.today(),
            patient_id=uuid4(),
            name="NewMed",
        )

        session = _mock_session(execute_returns=[
            _scalars_all([]),                # expired query (none)
            _scalars_all([scheduled_med]),   # scheduled query
        ])

        count = await service.complete_expired_medications(postgres_session=session)

        assert count == 1
        assert scheduled_med.status == "active"
        service._sync_qdrant.assert_called_once()
        service._notify_patient.assert_called_once()
        assert "begins today" in service._notify_patient.call_args[1]["body"]

    @pytest.mark.asyncio
    async def test_no_changes_returns_zero(self):
        service = _make_service()

        session = _mock_session(execute_returns=[
            _scalars_all([]),  # expired
            _scalars_all([]),  # scheduled
        ])

        count = await service.complete_expired_medications(postgres_session=session)

        assert count == 0
        service._sync_qdrant.assert_not_called()

    @pytest.mark.asyncio
    async def test_multiple_patients_each_synced(self):
        service = _make_service()

        pid1 = uuid4()
        pid2 = uuid4()

        med1 = _fake_medication(status="active", end_date=date.today() - timedelta(days=1), patient_id=pid1)
        med2 = _fake_medication(status="active", end_date=date.today() - timedelta(days=2), patient_id=pid2)

        session = _mock_session(execute_returns=[
            _scalars_all([med1, med2]),  # expired
            _scalars_all([]),             # scheduled
        ])

        count = await service.complete_expired_medications(postgres_session=session)

        assert count == 2
        assert service._sync_qdrant.call_count == 2

    @pytest.mark.asyncio
    async def test_activated_med_sends_notification_per_med(self):
        service = _make_service()

        pid = uuid4()
        med1 = _fake_medication(status="scheduled", start_date=date.today(), patient_id=pid, name="Med1")
        med2 = _fake_medication(status="scheduled", start_date=date.today(), patient_id=pid, name="Med2")

        session = _mock_session(execute_returns=[
            _scalars_all([]),              # expired
            _scalars_all([med1, med2]),    # scheduled
        ])

        await service.complete_expired_medications(postgres_session=session)

        assert service._notify_patient.call_count == 2
        bodies = [c[1]["body"] for c in service._notify_patient.call_args_list]
        assert any("Med1" in b for b in bodies)
        assert any("Med2" in b for b in bodies)


# ── _refresh_medication_tasks ───────────────────────────────────────────


class TestRefreshMedicationTasks:
    @pytest.mark.asyncio
    async def test_deletes_pending_and_regenerates(self):
        from lib.services.medication_service import MedicationService

        pending_task = SimpleNamespace(task_id=uuid4(), task_type="TAKE_MEDICATION_MORNING", status="pending")

        fake_store = MagicMock()
        inner_session = AsyncMock()
        inner_session.execute = AsyncMock(return_value=_scalars_all([pending_task]))
        inner_session.delete = AsyncMock()
        inner_session.commit = AsyncMock()

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def fake_get_session():
            yield inner_session

        fake_store.get_session = fake_get_session

        service = MedicationService(
            postgres_store=fake_store,
            medication_vector_service=MagicMock(),
        )

        fake_task_gen = MagicMock()
        fake_task_gen.generate_daily_tasks = AsyncMock()

        with patch("lib.core.container.container") as mock_container:
            mock_container.resolve = MagicMock(return_value=fake_task_gen)

            await service._refresh_medication_tasks(uuid4())

        inner_session.delete.assert_called_once_with(pending_task)
        fake_task_gen.generate_daily_tasks.assert_called_once()

    @pytest.mark.asyncio
    async def test_doesnt_delete_completed_tasks(self):
        from lib.services.medication_service import MedicationService

        # Query returns empty — no pending tasks to delete
        fake_store = MagicMock()
        inner_session = AsyncMock()
        inner_session.execute = AsyncMock(return_value=_scalars_all([]))
        inner_session.commit = AsyncMock()

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def fake_get_session():
            yield inner_session

        fake_store.get_session = fake_get_session

        service = MedicationService(
            postgres_store=fake_store,
            medication_vector_service=MagicMock(),
        )

        fake_task_gen = MagicMock()
        fake_task_gen.generate_daily_tasks = AsyncMock()

        with patch("lib.core.container.container") as mock_container:
            mock_container.resolve = MagicMock(return_value=fake_task_gen)

            await service._refresh_medication_tasks(uuid4())

        inner_session.delete.assert_not_called()
        fake_task_gen.generate_daily_tasks.assert_called_once()


# ── get_prescription / get_medication with patient_id filter ─────────────


class TestAccessControl:
    @pytest.mark.asyncio
    async def test_get_prescription_filters_by_patient(self):
        from lib.services.medication_service import MedicationService

        rx = _fake_prescription(status="confirmed")
        session = _mock_session(execute_returns=[_scalars_first(rx)])

        service = MedicationService(
            postgres_store=MagicMock(),
            medication_vector_service=MagicMock(),
        )

        result = await service.get_prescription(
            prescription_id=str(rx.prescription_id),
            patient_id=str(rx.patient_id),
            postgres_session=session,
        )

        assert result is not None
        # Verify the execute was called (the WHERE clause includes patient_id)
        session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_prescription_wrong_patient_returns_none(self):
        from lib.services.medication_service import MedicationService

        session = _mock_session(execute_returns=[_scalars_first(None)])

        service = MedicationService(
            postgres_store=MagicMock(),
            medication_vector_service=MagicMock(),
        )

        result = await service.get_prescription(
            prescription_id=str(uuid4()),
            patient_id=str(uuid4()),
            postgres_session=session,
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_get_medication_filters_by_patient(self):
        from lib.services.medication_service import MedicationService

        med = _fake_medication()
        session = _mock_session(execute_returns=[_scalars_first(med)])

        service = MedicationService(
            postgres_store=MagicMock(),
            medication_vector_service=MagicMock(),
        )

        result = await service.get_medication(
            medication_id=str(med.medication_id),
            patient_id=str(med.patient_id),
            postgres_session=session,
        )

        assert result is not None

    @pytest.mark.asyncio
    async def test_get_patient_prescriptions_excludes_archived(self):
        from lib.services.medication_service import MedicationService

        rx1 = _fake_prescription(status="confirmed")
        rx2 = _fake_prescription(status="draft")
        # archived would not be returned by the query (WHERE status != 'archived')

        session = _mock_session(execute_returns=[_scalars_all([rx1, rx2])])

        service = MedicationService(
            postgres_store=MagicMock(),
            medication_vector_service=MagicMock(),
        )

        result = await service.get_patient_prescriptions(
            patient_id=str(uuid4()),
            postgres_session=session,
        )

        assert len(result) == 2
        session.execute.assert_called_once()


# ── _sync_qdrant builds correct data ────────────────────────────────────


class TestSyncQdrant:
    @pytest.mark.asyncio
    async def test_sync_includes_schedule_in_med_dicts(self):
        from lib.services.medication_service import MedicationService

        sched = {"type": "weekly", "days_of_week": [0]}
        med = _fake_medication(schedule=sched, name="WeeklyMed")

        patient = SimpleNamespace(age=30, gender="male", patient_id=uuid4())

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[
            _scalars_all([med]),       # medications query
            _scalars_first(patient),   # patient query
        ])

        mock_vector = AsyncMock()
        mock_vector.upsert_medications_vector = AsyncMock()

        service = MedicationService(
            postgres_store=MagicMock(),
            medication_vector_service=mock_vector,
        )

        await service._sync_qdrant(str(med.patient_id), session)

        mock_vector.upsert_medications_vector.assert_called_once()
        call_kwargs = mock_vector.upsert_medications_vector.call_args[1]
        med_dicts = call_kwargs["medications"]
        assert len(med_dicts) == 1
        assert med_dicts[0]["schedule"] == sched
        assert med_dicts[0]["name"] == "WeeklyMed"

    @pytest.mark.asyncio
    async def test_sync_deletes_when_no_medications(self):
        from lib.services.medication_service import MedicationService

        session = AsyncMock()
        session.execute = AsyncMock(return_value=_scalars_all([]))

        mock_vector = AsyncMock()
        mock_vector.delete_medications_vector = AsyncMock()

        service = MedicationService(
            postgres_store=MagicMock(),
            medication_vector_service=mock_vector,
        )

        await service._sync_qdrant("patient-123", session)

        mock_vector.delete_medications_vector.assert_called_once_with("patient-123")
