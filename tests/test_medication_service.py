"""Tests for MedicationService — _initial_status, _is_same_medication, create/confirm/edit."""

from datetime import date, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from lib.schemas.medication import ConfirmedMedicine, MedicationDose, MedicationSchedule


# ── _initial_status (pure function, no mocking needed) ──────────────────


class TestInitialStatus:
    """Test MedicationService._initial_status via the schema directly."""

    def _status(self, **kwargs):
        from lib.services.medication_service import MedicationService
        defaults = {
            "name": "Test",
            "start_date": date.today(),
            "is_sos": False,
        }
        defaults.update(kwargs)
        med = ConfirmedMedicine(**defaults)
        return MedicationService._initial_status(med)

    def test_normal_active(self):
        assert self._status() == "active"

    def test_sos_as_needed(self):
        assert self._status(is_sos=True) == "as_needed"

    def test_end_date_in_past_is_completed(self):
        assert self._status(end_date=date.today() - timedelta(days=1)) == "completed"

    def test_end_date_today_is_active(self):
        # end_date < today triggers completed; end_date == today is still active
        assert self._status(end_date=date.today()) == "active"

    def test_start_date_in_future_is_scheduled(self):
        assert self._status(start_date=date.today() + timedelta(days=5)) == "scheduled"

    def test_start_date_today_is_active(self):
        assert self._status(start_date=date.today()) == "active"

    def test_sos_takes_priority_over_future_start(self):
        assert self._status(
            is_sos=True,
            start_date=date.today() + timedelta(days=5),
        ) == "as_needed"

    def test_sos_takes_priority_over_past_end(self):
        assert self._status(
            is_sos=True,
            end_date=date.today() - timedelta(days=1),
        ) == "as_needed"


# ── _is_same_medication (pure function) ─────────────────────────────────


class TestIsSameMedication:
    def _check(self, existing_kwargs, new_kwargs):
        from lib.services.medication_service import MedicationService

        existing = SimpleNamespace(
            strength="500mg",
            doses=[{"slot": "morning", "quantity": 1}],
            schedule=None,
            **existing_kwargs,
        )

        new_defaults = {
            "name": "Test",
            "start_date": date.today(),
            "strength": "500mg",
            "doses": [MedicationDose(slot="morning", quantity=1)],
            "schedule": None,
        }
        new_defaults.update(new_kwargs)
        new = ConfirmedMedicine(**new_defaults)

        new_doses_json = [d.model_dump() for d in new.doses]
        return MedicationService._is_same_medication(existing, new, new_doses_json)

    def test_identical_is_same(self):
        assert self._check({}, {}) is True

    def test_different_strength_not_same(self):
        assert self._check(
            {"strength": "500mg"},
            {"strength": "1000mg"},
        ) is False

    def test_strength_case_insensitive(self):
        assert self._check(
            {"strength": "500MG"},
            {"strength": "500mg"},
        ) is True

    def test_strength_whitespace_stripped(self):
        assert self._check(
            {"strength": " 500mg "},
            {"strength": "500mg"},
        ) is True

    def test_different_doses_not_same(self):
        assert self._check(
            {"doses": [{"slot": "morning", "quantity": 1}]},
            {"doses": [MedicationDose(slot="morning", quantity=1), MedicationDose(slot="evening", quantity=1)]},
        ) is False

    def test_different_quantity_not_same(self):
        assert self._check(
            {"doses": [{"slot": "morning", "quantity": 1}]},
            {"doses": [MedicationDose(slot="morning", quantity=0.5)]},
        ) is False

    def test_different_schedule_not_same(self):
        assert self._check(
            {"schedule": None},
            {"schedule": MedicationSchedule(type="weekly", days_of_week=[0])},
        ) is False

    def test_both_null_schedule_is_same(self):
        assert self._check(
            {"schedule": None},
            {"schedule": None},
        ) is True

    def test_same_weekly_schedule_is_same(self):
        assert self._check(
            {"schedule": {"type": "weekly", "days_of_week": [0, 2, 4]}},
            {"schedule": MedicationSchedule(type="weekly", days_of_week=[0, 2, 4])},
        ) is True

    def test_different_weekly_days_not_same(self):
        assert self._check(
            {"schedule": {"type": "weekly", "days_of_week": [0, 2, 4]}},
            {"schedule": MedicationSchedule(type="weekly", days_of_week=[1, 3, 5])},
        ) is False

    def test_null_strength_both_sides(self):
        assert self._check(
            {"strength": None},
            {"strength": None},
        ) is True


# ── Schema validation ───────────────────────────────────────────────────


class TestSchemaValidation:
    def test_end_date_before_start_date_rejected(self):
        with pytest.raises(ValueError, match="end_date must be on or after start_date"):
            ConfirmedMedicine(
                name="Test",
                start_date=date(2026, 5, 1),
                end_date=date(2026, 4, 1),
            )

    def test_end_date_equal_start_date_ok(self):
        med = ConfirmedMedicine(
            name="Test",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 1),
        )
        assert med.end_date == med.start_date

    def test_fractional_quantity_accepted(self):
        dose = MedicationDose(slot="morning", quantity=0.5)
        assert dose.quantity == 0.5

    def test_schedule_weekly_requires_days(self):
        with pytest.raises(ValueError, match="at least one day"):
            MedicationSchedule(type="weekly", days_of_week=[])

    def test_schedule_interval_requires_days(self):
        with pytest.raises(ValueError, match="interval_days"):
            MedicationSchedule(type="interval")

    def test_schedule_interval_requires_anchor(self):
        with pytest.raises(ValueError, match="interval_anchor"):
            MedicationSchedule(type="interval", interval_days=2)

    def test_schedule_interval_valid(self):
        sched = MedicationSchedule(
            type="interval",
            interval_days=2,
            interval_anchor=date(2026, 4, 10),
        )
        assert sched.interval_days == 2

    def test_schedule_null_means_daily(self):
        med = ConfirmedMedicine(
            name="Test",
            start_date=date.today(),
            schedule=None,
        )
        assert med.schedule is None
