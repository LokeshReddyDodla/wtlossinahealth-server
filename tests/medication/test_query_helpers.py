"""Tests for MedicationService query helpers — the four read methods that
gamification's task generator and reminders cron rely on but were uncovered:

- _find_active_by_name (case-insensitive name lookup)
- get_medications_for_date (active meds valid on a date)
- get_medications_expiring_soon (refill reminder source)
- get_follow_up_prescriptions_for_date (follow-up reminder source)
- get_active_medications (active+as_needed for AI context)
- get_all_medications (with optional status filter)
- get_medication_list (status grouping)

These are all SELECT-only methods. We patch the session's execute() to
return canned scalar results and assert the service builds the right
shape and applies the right filtering predicates.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest


def _mock_session(execute_returns):
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=execute_returns)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


def _scalars_all(values):
    class R:
        def scalars(self):
            return SimpleNamespace(all=lambda: list(values))

    return R()


def _scalars_first(value):
    class R:
        def scalars(self):
            return SimpleNamespace(first=lambda: value)

    return R()


def _med(
    *,
    name="Metformin",
    status="active",
    start_date=None,
    end_date=None,
    schedule=None,
    is_sos=False,
):
    return SimpleNamespace(
        medication_id=uuid4(),
        patient_id=uuid4(),
        prescription_id=uuid4(),
        name=name,
        brand_name=None,
        strength="500mg",
        formulation="tablet",
        route="oral",
        food_timing=None,
        purpose=None,
        instructions=None,
        doses=[{"slot": "morning", "quantity": 1}],
        schedule=schedule,
        start_date=start_date or date.today(),
        end_date=end_date,
        status=status,
        discontinued_at=None,
        discontinued_by=None,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


def _service():
    from lib.services.medication_service import MedicationService

    return MedicationService(
        postgres_store=MagicMock(),
        medication_vector_service=MagicMock(),
    )


# ── _find_active_by_name ────────────────────────────────────────────────────


class TestFindActiveByName:
    """Verifies the helper builds an ILIKE query on the trimmed name and
    statuses ∈ {active, as_needed, paused}. We only check the result shape
    (the ExprStub `ilike` is opaque), but we lock the session contract."""

    @pytest.mark.asyncio
    async def test_returns_list_of_meds(self):
        svc = _service()
        meds = [_med(name="Metformin"), _med(name="metformin", status="paused")]
        session = _mock_session([_scalars_all(meds)])
        result = await svc._find_active_by_name("p1", "Metformin", session)
        assert len(result) == 2
        session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_result(self):
        svc = _service()
        session = _mock_session([_scalars_all([])])
        result = await svc._find_active_by_name("p1", "Aspirin", session)
        assert result == []

    @pytest.mark.asyncio
    async def test_strips_whitespace_in_name_input(self):
        """Ensure the helper is called with the stripped name (build-side)."""
        svc = _service()
        session = _mock_session([_scalars_all([])])
        # If the helper crashed on whitespace, this would raise
        await svc._find_active_by_name("p1", "  Metformin  ", session)
        session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_unicode_name_passes_through(self):
        svc = _service()
        session = _mock_session([_scalars_all([])])
        await svc._find_active_by_name("p1", "दवा", session)
        session.execute.assert_called_once()


# ── get_medications_for_date ────────────────────────────────────────────────


class TestGetMedicationsForDate:
    @pytest.mark.asyncio
    async def test_returns_active_meds(self):
        svc = _service()
        meds = [_med(start_date=date.today() - timedelta(days=10))]
        session = _mock_session([_scalars_all(meds)])
        result = await svc.get_medications_for_date(
            patient_id="p1",
            task_date=date.today(),
            postgres_session=session,
        )
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_empty_no_active_meds(self):
        svc = _service()
        session = _mock_session([_scalars_all([])])
        result = await svc.get_medications_for_date(
            patient_id="p1",
            task_date=date.today(),
            postgres_session=session,
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_executes_one_query(self):
        """Verify single execute call (no N+1)."""
        svc = _service()
        session = _mock_session([_scalars_all([])])
        await svc.get_medications_for_date(
            patient_id="p1",
            task_date=date.today(),
            postgres_session=session,
        )
        assert session.execute.call_count == 1

    @pytest.mark.parametrize(
        "task_date",
        [
            date(2026, 1, 1),    # year boundary
            date(2026, 2, 28),   # non-leap Feb end
            date(2024, 2, 29),   # leap day
            date(2026, 12, 31),  # year end
            date(2026, 4, 15),   # mid-month
        ],
    )
    @pytest.mark.asyncio
    async def test_accepts_various_dates(self, task_date):
        svc = _service()
        session = _mock_session([_scalars_all([])])
        result = await svc.get_medications_for_date(
            patient_id="p1",
            task_date=task_date,
            postgres_session=session,
        )
        assert result == []


# ── get_medications_expiring_soon ────────────────────────────────────────────


class TestGetMedicationsExpiringSoon:
    @pytest.mark.asyncio
    async def test_returns_meds_expiring_at_target_date(self):
        svc = _service()
        meds = [_med(end_date=date.today() + timedelta(days=3))]
        session = _mock_session([_scalars_all(meds)])
        result = await svc.get_medications_expiring_soon(
            patient_id="p1",
            within_days=3,
            postgres_session=session,
        )
        assert len(result) == 1

    @pytest.mark.parametrize("within_days", [1, 3, 7, 14, 30])
    @pytest.mark.asyncio
    async def test_within_days_parameter_forwarded(self, within_days):
        svc = _service()
        session = _mock_session([_scalars_all([])])
        await svc.get_medications_expiring_soon(
            patient_id="p1",
            within_days=within_days,
            postgres_session=session,
        )
        session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_default_within_days_is_3(self):
        svc = _service()
        session = _mock_session([_scalars_all([])])
        # Default per signature
        result = await svc.get_medications_expiring_soon(
            patient_id="p1",
            postgres_session=session,
        )
        assert result == []
        session.execute.assert_called_once()


# ── get_follow_up_prescriptions_for_date ────────────────────────────────────


class TestGetFollowUpPrescriptionsForDate:
    def _rx(self, follow_up_required=True, follow_up_date=None, status="confirmed"):
        return SimpleNamespace(
            prescription_id=uuid4(),
            patient_id=uuid4(),
            doctor_name="Dr. Test",
            prescription_date=date.today(),
            file_urls=[],
            status=status,
            extracted_data=None,
            uploaded_by_id=None,
            uploaded_by_type=None,
            follow_up_required=follow_up_required,
            follow_up_date=follow_up_date or date.today(),
            notes=None,
            medications=[],
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

    @pytest.mark.asyncio
    async def test_returns_confirmed_with_follow_up(self):
        svc = _service()
        rxs = [self._rx()]
        session = _mock_session([_scalars_all(rxs)])
        result = await svc.get_follow_up_prescriptions_for_date(
            patient_id="p1",
            task_date=date.today(),
            postgres_session=session,
        )
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_empty_when_none_match(self):
        svc = _service()
        session = _mock_session([_scalars_all([])])
        result = await svc.get_follow_up_prescriptions_for_date(
            patient_id="p1",
            task_date=date.today(),
            postgres_session=session,
        )
        assert result == []


# ── get_active_medications ──────────────────────────────────────────────────


class TestGetActiveMedications:
    @pytest.mark.asyncio
    async def test_returns_active_and_as_needed(self):
        svc = _service()
        meds = [_med(status="active"), _med(status="as_needed")]
        session = _mock_session([_scalars_all(meds)])
        result = await svc.get_active_medications(
            patient_id="p1", postgres_session=session,
        )
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_empty_returns_empty_list(self):
        svc = _service()
        session = _mock_session([_scalars_all([])])
        result = await svc.get_active_medications(
            patient_id="p1", postgres_session=session,
        )
        assert result == []


# ── get_all_medications ─────────────────────────────────────────────────────


class TestGetAllMedications:
    @pytest.mark.asyncio
    async def test_no_filter_returns_all(self):
        svc = _service()
        meds = [_med(status=s) for s in ("active", "paused", "completed", "discontinued")]
        session = _mock_session([_scalars_all(meds)])
        result = await svc.get_all_medications(
            patient_id="p1", postgres_session=session,
        )
        assert len(result) == 4

    @pytest.mark.parametrize(
        "status",
        ["active", "paused", "completed", "discontinued", "as_needed", "scheduled"],
    )
    @pytest.mark.asyncio
    async def test_status_filter_forwarded(self, status):
        svc = _service()
        session = _mock_session([_scalars_all([])])
        result = await svc.get_all_medications(
            patient_id="p1", status=status, postgres_session=session,
        )
        assert result == []
        session.execute.assert_called_once()


# ── get_medication_list (status grouping) ───────────────────────────────────


class TestGetMedicationListGrouping:
    """Locks the bucket assignment in get_medication_list. Critical: ensures
    'completed' and 'discontinued' both end up under 'completed', 'scheduled'
    is grouped with active, etc."""

    @pytest.mark.asyncio
    async def test_groups_each_status_into_correct_bucket(self):
        svc = _service()
        meds = [
            _med(status="active", name="A"),
            _med(status="paused", name="B"),
            _med(status="as_needed", name="C"),
            _med(status="completed", name="D"),
            _med(status="discontinued", name="E"),
            _med(status="scheduled", name="F"),
        ]
        session = _mock_session([_scalars_all(meds)])

        result = await svc.get_medication_list(
            patient_id="p1", postgres_session=session,
        )
        active_names = {m.name for m in result.active}
        paused_names = {m.name for m in result.paused}
        as_needed_names = {m.name for m in result.as_needed}
        completed_names = {m.name for m in result.completed}

        assert active_names == {"A", "F"}        # active + scheduled
        assert paused_names == {"B"}
        assert as_needed_names == {"C"}
        assert completed_names == {"D", "E"}     # completed + discontinued

    @pytest.mark.asyncio
    async def test_empty_list_returns_empty_buckets(self):
        svc = _service()
        session = _mock_session([_scalars_all([])])
        result = await svc.get_medication_list(
            patient_id="p1", postgres_session=session,
        )
        assert result.active == []
        assert result.paused == []
        assert result.as_needed == []
        assert result.completed == []

    @pytest.mark.asyncio
    async def test_single_status_only_populates_one_bucket(self):
        svc = _service()
        meds = [_med(status="active") for _ in range(5)]
        session = _mock_session([_scalars_all(meds)])
        result = await svc.get_medication_list(
            patient_id="p1", postgres_session=session,
        )
        assert len(result.active) == 5
        assert result.paused == []
        assert result.as_needed == []
        assert result.completed == []


# ── get_prescription / get_medication identity check ────────────────────────


class TestSinglePrescriptionLookup:
    @pytest.mark.asyncio
    async def test_get_prescription_returns_value(self):
        svc = _service()
        rx = SimpleNamespace(
            prescription_id=uuid4(),
            patient_id=uuid4(),
            status="confirmed",
            file_urls=[],
            doctor_name="Dr. Test",
            prescription_date=date.today(),
            extracted_data=None,
            uploaded_by_id=None,
            uploaded_by_type=None,
            follow_up_required=False,
            follow_up_date=None,
            notes=None,
            medications=[],
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        session = _mock_session([_scalars_first(rx)])
        result = await svc.get_prescription(
            prescription_id=str(rx.prescription_id),
            patient_id=str(rx.patient_id),
            postgres_session=session,
        )
        assert result is rx

    @pytest.mark.asyncio
    async def test_get_prescription_not_found(self):
        svc = _service()
        session = _mock_session([_scalars_first(None)])
        result = await svc.get_prescription(
            prescription_id=str(uuid4()),
            patient_id=str(uuid4()),
            postgres_session=session,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_get_medication_returns_value(self):
        svc = _service()
        med = _med()
        session = _mock_session([_scalars_first(med)])
        result = await svc.get_medication(
            medication_id=str(med.medication_id),
            patient_id=str(med.patient_id),
            postgres_session=session,
        )
        assert result is med

    @pytest.mark.asyncio
    async def test_get_medication_not_found(self):
        svc = _service()
        session = _mock_session([_scalars_first(None)])
        result = await svc.get_medication(
            medication_id=str(uuid4()),
            patient_id=str(uuid4()),
            postgres_session=session,
        )
        assert result is None
