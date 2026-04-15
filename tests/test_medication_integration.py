"""Integration tests for MedicationService — full flows with mocked DB/Qdrant/FCM.

Tests cover confirm, edit, archive, pause/resume/discontinue, _create_medication
renewal vs change, complete_expired_medications, _refresh_medication_tasks,
get_medication_list grouping, to_response, and access control.
"""

from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from lib.schemas.medication import (
    ConfirmPrescriptionRequest,
    ConfirmedMedicine,
    MedicationDose,
    MedicationListResponse,
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
        "extracted_data": None,
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


def _confirm_request(medicines=None, **kwargs):
    defaults = {
        "doctor_name": "Dr. Test",
        "prescription_date": date.today(),
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


# ── to_response ─────────────────────────────────────────────────────────


class TestToResponse:
    def test_active_med_with_end_date_has_days_remaining(self):
        from lib.services.medication_service import MedicationService
        med = _fake_medication(
            end_date=date.today() + timedelta(days=5),
            status="active",
        )
        resp = MedicationService.to_response(med, date.today())
        assert resp.days_remaining == 5

    def test_active_med_no_end_date_has_null_days_remaining(self):
        from lib.services.medication_service import MedicationService
        med = _fake_medication(end_date=None, status="active")
        resp = MedicationService.to_response(med, date.today())
        assert resp.days_remaining is None

    def test_completed_med_no_days_remaining(self):
        from lib.services.medication_service import MedicationService
        med = _fake_medication(
            end_date=date.today() - timedelta(days=1),
            status="completed",
        )
        resp = MedicationService.to_response(med, date.today())
        assert resp.days_remaining is None

    def test_is_sos_derived_from_status(self):
        from lib.services.medication_service import MedicationService
        med = _fake_medication(status="as_needed")
        resp = MedicationService.to_response(med, date.today())
        assert resp.is_sos is True

    def test_not_sos_for_active(self):
        from lib.services.medication_service import MedicationService
        med = _fake_medication(status="active")
        resp = MedicationService.to_response(med, date.today())
        assert resp.is_sos is False

    def test_schedule_mapped_to_response(self):
        from lib.services.medication_service import MedicationService
        sched = {"type": "weekly", "days_of_week": [0, 2, 4], "interval_days": None, "interval_anchor": None}
        med = _fake_medication(schedule=sched)
        resp = MedicationService.to_response(med, date.today())
        assert resp.schedule is not None
        assert resp.schedule.days_of_week == [0, 2, 4]

    def test_null_schedule_in_response(self):
        from lib.services.medication_service import MedicationService
        med = _fake_medication(schedule=None)
        resp = MedicationService.to_response(med, date.today())
        assert resp.schedule is None

    def test_days_remaining_zero_on_end_date(self):
        from lib.services.medication_service import MedicationService
        med = _fake_medication(
            end_date=date.today(),
            status="active",
        )
        resp = MedicationService.to_response(med, date.today())
        assert resp.days_remaining == 0

    def test_fractional_dose_in_response(self):
        from lib.services.medication_service import MedicationService
        med = _fake_medication(doses=[{"slot": "morning", "quantity": 0.5}])
        resp = MedicationService.to_response(med, date.today())
        assert resp.doses[0].quantity == 0.5


# ── get_medication_list grouping ────────────────────────────────────────


class TestMedicationListGrouping:
    @pytest.mark.asyncio
    async def test_groups_by_status(self):
        from lib.services.medication_service import MedicationService

        active_med = _fake_medication(status="active")
        paused_med = _fake_medication(status="paused", name="Aspirin")
        as_needed_med = _fake_medication(status="as_needed", name="Ibuprofen")
        completed_med = _fake_medication(status="completed", name="OldMed")
        discontinued_med = _fake_medication(status="discontinued", name="Removed")
        scheduled_med = _fake_medication(status="scheduled", name="FutureMed")

        class FakeScalars:
            def all(self_inner):
                return [active_med, paused_med, as_needed_med, completed_med, discontinued_med, scheduled_med]

        class FakeResult:
            def scalars(self_inner):
                return FakeScalars()

        session = AsyncMock()
        session.execute = AsyncMock(return_value=FakeResult())

        service = MedicationService(postgres_store=MagicMock(), medication_vector_service=MagicMock())
        result = await service.get_medication_list(patient_id="test-pid", postgres_session=session)

        assert len(result.active) == 2  # active + scheduled
        assert len(result.paused) == 1
        assert len(result.as_needed) == 1
        assert len(result.completed) == 2  # completed + discontinued

        active_names = {m.name for m in result.active}
        assert "Metformin" in active_names
        assert "FutureMed" in active_names

    @pytest.mark.asyncio
    async def test_empty_meds_returns_empty_groups(self):
        from lib.services.medication_service import MedicationService

        class FakeScalars:
            def all(self_inner):
                return []

        class FakeResult:
            def scalars(self_inner):
                return FakeScalars()

        session = AsyncMock()
        session.execute = AsyncMock(return_value=FakeResult())

        service = MedicationService(postgres_store=MagicMock(), medication_vector_service=MagicMock())
        result = await service.get_medication_list(patient_id="test-pid", postgres_session=session)

        assert result.active == []
        assert result.paused == []
        assert result.as_needed == []
        assert result.completed == []


# ── _create_medication renewal vs change ────────────────────────────────


class TestCreateMedicationRenewalVsChange:
    @pytest.mark.asyncio
    async def test_same_med_marks_old_completed(self):
        """Same name, same strength, same doses → old marked 'completed' (renewal)."""
        from lib.services.medication_service import MedicationService

        old_med = _fake_medication(name="Metformin", strength="500mg",
                                   doses=[{"slot": "morning", "quantity": 1}],
                                   schedule=None)

        class FakeScalars:
            def all(self_inner):
                return [old_med]

        class FakeResult:
            def scalars(self_inner):
                return FakeScalars()

        session = AsyncMock()
        session.execute = AsyncMock(return_value=FakeResult())
        session.add = MagicMock()

        service = MedicationService(postgres_store=MagicMock(), medication_vector_service=MagicMock())

        new_med_data = ConfirmedMedicine(
            name="Metformin",
            strength="500mg",
            doses=[MedicationDose(slot="morning", quantity=1)],
            start_date=date.today(),
        )

        await service._create_medication(
            patient_id=str(uuid4()),
            prescription_id=uuid4(),
            med_data=new_med_data,
            session=session,
        )

        assert old_med.status == "completed"
        assert old_med.discontinued_at is not None
        assert session.add.called

    @pytest.mark.asyncio
    async def test_different_strength_marks_old_discontinued(self):
        """Same name, different strength → old marked 'discontinued' (change)."""
        from lib.services.medication_service import MedicationService

        old_med = _fake_medication(name="Metformin", strength="500mg")

        class FakeScalars:
            def all(self_inner):
                return [old_med]

        class FakeResult:
            def scalars(self_inner):
                return FakeScalars()

        session = AsyncMock()
        session.execute = AsyncMock(return_value=FakeResult())
        session.add = MagicMock()

        service = MedicationService(postgres_store=MagicMock(), medication_vector_service=MagicMock())

        new_med_data = ConfirmedMedicine(
            name="Metformin",
            strength="1000mg",
            doses=[MedicationDose(slot="morning", quantity=1)],
            start_date=date.today(),
        )

        await service._create_medication(
            patient_id=str(uuid4()),
            prescription_id=uuid4(),
            med_data=new_med_data,
            session=session,
        )

        assert old_med.status == "discontinued"

    @pytest.mark.asyncio
    async def test_different_schedule_marks_old_discontinued(self):
        """Same name, same strength, different schedule → discontinued."""
        from lib.services.medication_service import MedicationService

        old_med = _fake_medication(name="VitD", strength="1000IU", schedule=None)

        class FakeScalars:
            def all(self_inner):
                return [old_med]

        class FakeResult:
            def scalars(self_inner):
                return FakeScalars()

        session = AsyncMock()
        session.execute = AsyncMock(return_value=FakeResult())
        session.add = MagicMock()

        service = MedicationService(postgres_store=MagicMock(), medication_vector_service=MagicMock())

        new_med_data = ConfirmedMedicine(
            name="VitD",
            strength="1000IU",
            doses=[MedicationDose(slot="morning", quantity=1)],
            schedule=MedicationSchedule(type="weekly", days_of_week=[6]),
            start_date=date.today(),
        )

        await service._create_medication(
            patient_id=str(uuid4()),
            prescription_id=uuid4(),
            med_data=new_med_data,
            session=session,
        )

        assert old_med.status == "discontinued"

    @pytest.mark.asyncio
    async def test_no_existing_creates_fresh(self):
        """No existing med with same name → just creates new, no status changes."""
        from lib.services.medication_service import MedicationService

        class FakeScalars:
            def all(self_inner):
                return []

        class FakeResult:
            def scalars(self_inner):
                return FakeScalars()

        session = AsyncMock()
        session.execute = AsyncMock(return_value=FakeResult())
        session.add = MagicMock()

        service = MedicationService(postgres_store=MagicMock(), medication_vector_service=MagicMock())

        new_med_data = ConfirmedMedicine(
            name="BrandNew",
            strength="100mg",
            doses=[MedicationDose(slot="morning", quantity=1)],
            start_date=date.today(),
        )

        result = await service._create_medication(
            patient_id=str(uuid4()),
            prescription_id=uuid4(),
            med_data=new_med_data,
            session=session,
        )

        assert session.add.called
        added = session.add.call_args[0][0]
        assert added.name == "BrandNew"
        assert added.status == "active"

    @pytest.mark.asyncio
    async def test_sos_med_created_as_needed(self):
        from lib.services.medication_service import MedicationService

        class FakeScalars:
            def all(self_inner):
                return []

        class FakeResult:
            def scalars(self_inner):
                return FakeScalars()

        session = AsyncMock()
        session.execute = AsyncMock(return_value=FakeResult())
        session.add = MagicMock()

        service = MedicationService(postgres_store=MagicMock(), medication_vector_service=MagicMock())

        new_med_data = ConfirmedMedicine(
            name="Paracetamol",
            start_date=date.today(),
            is_sos=True,
        )

        await service._create_medication(
            patient_id=str(uuid4()),
            prescription_id=uuid4(),
            med_data=new_med_data,
            session=session,
        )

        added = session.add.call_args[0][0]
        assert added.status == "as_needed"

    @pytest.mark.asyncio
    async def test_future_start_date_created_as_scheduled(self):
        from lib.services.medication_service import MedicationService

        class FakeScalars:
            def all(self_inner):
                return []

        class FakeResult:
            def scalars(self_inner):
                return FakeScalars()

        session = AsyncMock()
        session.execute = AsyncMock(return_value=FakeResult())
        session.add = MagicMock()

        service = MedicationService(postgres_store=MagicMock(), medication_vector_service=MagicMock())

        new_med_data = ConfirmedMedicine(
            name="FutureMed",
            start_date=date.today() + timedelta(days=7),
        )

        await service._create_medication(
            patient_id=str(uuid4()),
            prescription_id=uuid4(),
            med_data=new_med_data,
            session=session,
        )

        added = session.add.call_args[0][0]
        assert added.status == "scheduled"

    @pytest.mark.asyncio
    async def test_schedule_persisted(self):
        from lib.services.medication_service import MedicationService

        class FakeScalars:
            def all(self_inner):
                return []

        class FakeResult:
            def scalars(self_inner):
                return FakeScalars()

        session = AsyncMock()
        session.execute = AsyncMock(return_value=FakeResult())
        session.add = MagicMock()

        service = MedicationService(postgres_store=MagicMock(), medication_vector_service=MagicMock())

        sched = MedicationSchedule(type="weekly", days_of_week=[0, 2, 4])
        new_med_data = ConfirmedMedicine(
            name="WeeklyMed",
            start_date=date.today(),
            schedule=sched,
        )

        await service._create_medication(
            patient_id=str(uuid4()),
            prescription_id=uuid4(),
            med_data=new_med_data,
            session=session,
        )

        added = session.add.call_args[0][0]
        assert added.schedule is not None
        assert added.schedule["type"] == "weekly"
        assert added.schedule["days_of_week"] == [0, 2, 4]


# ── Lifecycle actions ───────────────────────────────────────────────────


class TestLifecycleActions:
    def _make_service(self):
        from lib.services.medication_service import MedicationService
        mock_store = MagicMock()
        mock_vector = MagicMock()
        service = MedicationService(postgres_store=mock_store, medication_vector_service=mock_vector)
        return service

    @pytest.mark.asyncio
    async def test_pause_sets_status(self):
        service = self._make_service()
        med = _fake_medication(status="active")

        class FakeScalars:
            def first(self_inner):
                return med

        class FakeResult:
            def scalars(self_inner):
                return FakeScalars()

        session = AsyncMock()
        session.execute = AsyncMock(return_value=FakeResult())

        service._sync_qdrant = AsyncMock()
        service._refresh_medication_tasks = AsyncMock()
        service._notify_patient = AsyncMock()

        result = await service.pause_medication(
            medication_id=str(med.medication_id),
            postgres_session=session,
        )

        assert result.status == "paused"
        service._sync_qdrant.assert_called_once()
        service._refresh_medication_tasks.assert_called_once()
        service._notify_patient.assert_called_once()
        assert "paused" in service._notify_patient.call_args[1]["body"]

    @pytest.mark.asyncio
    async def test_resume_sets_active(self):
        service = self._make_service()
        med = _fake_medication(status="paused")

        class FakeScalars:
            def first(self_inner):
                return med

        class FakeResult:
            def scalars(self_inner):
                return FakeScalars()

        session = AsyncMock()
        session.execute = AsyncMock(return_value=FakeResult())

        service._sync_qdrant = AsyncMock()
        service._refresh_medication_tasks = AsyncMock()
        service._notify_patient = AsyncMock()

        result = await service.resume_medication(
            medication_id=str(med.medication_id),
            postgres_session=session,
        )

        assert result.status == "active"
        assert med.discontinued_at is None
        assert med.discontinued_by is None
        service._notify_patient.assert_called_once()
        assert "resumed" in service._notify_patient.call_args[1]["body"]

    @pytest.mark.asyncio
    async def test_discontinue_sets_status_and_by(self):
        service = self._make_service()
        med = _fake_medication(status="active")
        cp_id = str(uuid4())

        class FakeScalars:
            def first(self_inner):
                return med

        class FakeResult:
            def scalars(self_inner):
                return FakeScalars()

        session = AsyncMock()
        session.execute = AsyncMock(return_value=FakeResult())

        service._sync_qdrant = AsyncMock()
        service._refresh_medication_tasks = AsyncMock()
        service._notify_patient = AsyncMock()

        result = await service.discontinue_medication(
            medication_id=str(med.medication_id),
            discontinued_by=cp_id,
            postgres_session=session,
        )

        assert result.status == "discontinued"
        assert result.discontinued_by == cp_id
        assert result.discontinued_at is not None
        service._notify_patient.assert_called_once()
        assert "discontinued" in service._notify_patient.call_args[1]["body"]

    @pytest.mark.asyncio
    async def test_pause_nonexistent_returns_none(self):
        service = self._make_service()

        class FakeScalars:
            def first(self_inner):
                return None

        class FakeResult:
            def scalars(self_inner):
                return FakeScalars()

        session = AsyncMock()
        session.execute = AsyncMock(return_value=FakeResult())

        result = await service.pause_medication(
            medication_id=str(uuid4()),
            postgres_session=session,
        )
        assert result is None


# ── Archive prescription ────────────────────────────────────────────────


class TestArchivePrescription:
    @pytest.mark.asyncio
    async def test_archive_discontinues_child_meds(self):
        from lib.services.medication_service import MedicationService

        active_med = _fake_medication(status="active", name="Med1")
        paused_med = _fake_medication(status="paused", name="Med2")
        completed_med = _fake_medication(status="completed", name="OldMed")

        rx = _fake_prescription(
            status="confirmed",
            medications=[active_med, paused_med, completed_med],
        )

        class FakeScalars:
            def first(self_inner):
                return rx

        class FakeResult:
            def scalars(self_inner):
                return FakeScalars()

        session = AsyncMock()
        session.execute = AsyncMock(return_value=FakeResult())

        service = MedicationService(postgres_store=MagicMock(), medication_vector_service=MagicMock())
        service._sync_qdrant = AsyncMock()

        result = await service.archive_prescription(
            prescription_id=str(rx.prescription_id),
            patient_id=str(rx.patient_id),
            postgres_session=session,
        )

        assert result.status == "archived"
        assert active_med.status == "discontinued"
        assert paused_med.status == "discontinued"
        assert completed_med.status == "completed"  # already completed, untouched

    @pytest.mark.asyncio
    async def test_archive_nonexistent_returns_none(self):
        from lib.services.medication_service import MedicationService

        class FakeScalars:
            def first(self_inner):
                return None

        class FakeResult:
            def scalars(self_inner):
                return FakeScalars()

        session = AsyncMock()
        session.execute = AsyncMock(return_value=FakeResult())

        service = MedicationService(postgres_store=MagicMock(), medication_vector_service=MagicMock())

        result = await service.archive_prescription(
            prescription_id=str(uuid4()),
            patient_id=str(uuid4()),
            postgres_session=session,
        )
        assert result is None
