"""Exhaustive permutation matrices for medication pure functions and schema validators.

Extends existing coverage in test_medication_service.py and test_medication_scheduling.py
with boundary/edge cases that weren't previously parametrized:

- _initial_status full truth table (is_sos × start × end × today)
- _is_same_medication strength normalisation, dose reordering, full null/empty matrix
- _is_medication_due negative anchors, malformed payloads, DST-agnostic date math
- MedicationSchedule / MedicationDose / ConfirmedMedicine Pydantic validator permutations

Pure-function tests — no async, no DB, no mocks.
"""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from lib.schemas.medication import (
    ConfirmedMedicine,
    MedicationDose,
    MedicationSchedule,
)
from lib.services.medication_service import MedicationService


TODAY = date(2026, 4, 15)  # Wednesday; used as fixed reference for permutations
PAST = TODAY - timedelta(days=30)
FUTURE = TODAY + timedelta(days=30)


# ── _initial_status truth table ─────────────────────────────────────────────


def _make_cm(
    *,
    is_sos: bool = False,
    start_date: date = TODAY,
    end_date: date | None = None,
    **extra,
) -> ConfirmedMedicine:
    return ConfirmedMedicine(
        name=extra.pop("name", "Test"),
        start_date=start_date,
        end_date=end_date,
        is_sos=is_sos,
        **extra,
    )


@pytest.mark.parametrize(
    "is_sos,start_offset,end_offset,expected",
    [
        # is_sos wins regardless of dates
        (True, -30, None, "as_needed"),
        (True, -30, -1, "as_needed"),   # sos beats expired end_date
        (True, 30, None, "as_needed"),  # sos beats future start
        (True, 30, 60, "as_needed"),
        # Not sos — end_date rules apply first
        (False, -30, -1, "completed"),  # end yesterday
        (False, -30, -30, "completed"), # end month ago
        (False, -30, 0, "active"),       # end today (inclusive)
        (False, -30, 30, "active"),      # end future
        (False, -30, None, "active"),    # no end
        # start_date in future → scheduled (only when end_date isn't past)
        (False, 1, None, "scheduled"),
        (False, 30, None, "scheduled"),
        (False, 30, 60, "scheduled"),
        (False, 1, 30, "scheduled"),
        # start today, no end → active
        (False, 0, None, "active"),
        (False, 0, 0, "active"),
        (False, 0, 30, "active"),
    ],
)
def test_initial_status_truth_table(monkeypatch, is_sos, start_offset, end_offset, expected):
    """Lock the full (is_sos × start × end) matrix for _initial_status."""
    monkeypatch.setattr(
        "lib.services.medication_service.date",
        SimpleNamespace(today=lambda: TODAY),
    )
    start = TODAY + timedelta(days=start_offset)
    end = TODAY + timedelta(days=end_offset) if end_offset is not None else None
    med = _make_cm(is_sos=is_sos, start_date=start, end_date=end)
    assert MedicationService._initial_status(med) == expected


# ── _is_same_medication permutations ────────────────────────────────────────


def _existing(**overrides):
    """Build a SimpleNamespace mimicking the ORM row with sensible defaults."""
    defaults = {
        "strength": "500mg",
        "doses": [{"slot": "morning", "quantity": 1}],
        "schedule": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _new(**overrides) -> ConfirmedMedicine:
    defaults = {
        "name": "Test",
        "start_date": TODAY,
        "strength": "500mg",
        "doses": [MedicationDose(slot="morning", quantity=1)],
        "schedule": None,
    }
    defaults.update(overrides)
    return ConfirmedMedicine(**defaults)


def _same(existing, new) -> bool:
    doses_json = [d.model_dump() for d in new.doses]
    return MedicationService._is_same_medication(existing, new, doses_json)


class TestIsSameMedicationPermutations:
    """Coverage extends test_medication_service.TestIsSameMedication with
    reordering, whitespace, case mixing, empty doses, and null-side edges."""

    @pytest.mark.parametrize(
        "old_strength,new_strength,expected",
        [
            ("500mg", "500mg", True),
            ("500mg", "500MG", True),         # case
            ("500MG", "500mg", True),
            ("500mg", " 500mg", True),        # leading ws
            ("500mg ", "500mg", True),        # trailing ws
            ("  500mg  ", "500mg", True),     # double ws
            ("500mg", "500 mg", False),       # internal ws differs — not stripped
            ("500mg", "1000mg", False),
            ("500mg", "0.5g", False),         # units differ
            (None, None, True),               # both null
            (None, "500mg", False),
            ("500mg", None, False),
            ("", "", True),                   # both empty
            ("", None, True),                 # empty str == null after strip
            ("500mg", "", False),
        ],
    )
    def test_strength_normalisation(self, old_strength, new_strength, expected):
        assert _same(_existing(strength=old_strength), _new(strength=new_strength)) is expected

    @pytest.mark.parametrize(
        "old_doses,new_doses,expected",
        [
            # identical
            (
                [{"slot": "morning", "quantity": 1}],
                [MedicationDose(slot="morning", quantity=1)],
                True,
            ),
            # reordered multi-slot — sort-invariant
            (
                [
                    {"slot": "evening", "quantity": 1},
                    {"slot": "morning", "quantity": 1},
                ],
                [
                    MedicationDose(slot="morning", quantity=1),
                    MedicationDose(slot="evening", quantity=1),
                ],
                True,
            ),
            # different quantity
            (
                [{"slot": "morning", "quantity": 1}],
                [MedicationDose(slot="morning", quantity=0.5)],
                False,
            ),
            # fractional matching
            (
                [{"slot": "morning", "quantity": 0.5}],
                [MedicationDose(slot="morning", quantity=0.5)],
                True,
            ),
            # missing slot (different set)
            (
                [{"slot": "morning", "quantity": 1}],
                [
                    MedicationDose(slot="morning", quantity=1),
                    MedicationDose(slot="evening", quantity=1),
                ],
                False,
            ),
            # default quantity (existing missing quantity key) defaults to 1
            (
                [{"slot": "morning"}],
                [MedicationDose(slot="morning", quantity=1)],
                True,
            ),
            # empty both sides
            ([], [], True),
        ],
    )
    def test_dose_comparisons(self, old_doses, new_doses, expected):
        assert _same(_existing(doses=old_doses), _new(doses=new_doses)) is expected

    @pytest.mark.parametrize(
        "old_sched,new_sched,expected",
        [
            (None, None, True),
            # empty dict vs None → Python `{} != {}` but existing is None; code does `existing.schedule or {}` → both become {}
            (None, None, True),
            # weekly equal
            (
                {"type": "weekly", "days_of_week": [0, 2, 4], "interval_days": None, "interval_anchor": None},
                MedicationSchedule(type="weekly", days_of_week=[0, 2, 4]),
                True,
            ),
            # weekly diff days
            (
                {"type": "weekly", "days_of_week": [0], "interval_days": None, "interval_anchor": None},
                MedicationSchedule(type="weekly", days_of_week=[1]),
                False,
            ),
            # interval equal
            (
                {"type": "interval", "days_of_week": [0, 1, 2, 3, 4, 5, 6],
                 "interval_days": 2, "interval_anchor": "2026-04-10"},
                MedicationSchedule(
                    type="interval", interval_days=2, interval_anchor=date(2026, 4, 10),
                ),
                True,
            ),
            # interval diff anchor
            (
                {"type": "interval", "days_of_week": [0, 1, 2, 3, 4, 5, 6],
                 "interval_days": 2, "interval_anchor": "2026-04-10"},
                MedicationSchedule(
                    type="interval", interval_days=2, interval_anchor=date(2026, 4, 11),
                ),
                False,
            ),
            # interval vs weekly
            (
                {"type": "weekly", "days_of_week": [0, 1, 2, 3, 4, 5, 6],
                 "interval_days": None, "interval_anchor": None},
                MedicationSchedule(
                    type="interval", interval_days=2, interval_anchor=date(2026, 4, 10),
                ),
                False,
            ),
            # one-sided null
            (
                None,
                MedicationSchedule(type="weekly", days_of_week=[0]),
                False,
            ),
            (
                {"type": "weekly", "days_of_week": [0], "interval_days": None, "interval_anchor": None},
                None,  # i.e. new.schedule is None → compared against {}
                False,
            ),
        ],
    )
    def test_schedule_comparisons(self, old_sched, new_sched, expected):
        if new_sched is None:
            new = _new(schedule=None)
        else:
            new = _new(schedule=new_sched)
        assert _same(_existing(schedule=old_sched), new) is expected


# ── _is_medication_due edge cases ───────────────────────────────────────────


@pytest.fixture
def _is_due():
    """Expose the staticmethod without needing a task_generator fixture."""
    # Import lazily to avoid heavy module graph during collection
    from lib.services.gamification.task_generator import TaskGeneratorService

    return TaskGeneratorService._is_medication_due


def _med_stub(schedule):
    return SimpleNamespace(schedule=schedule)


class TestIsMedicationDueEdgeCases:
    """Extends test_medication_scheduling.TestIsMedicationDue with malformed
    payloads, boundary dates, and negative-modulo anchor scenarios."""

    @pytest.mark.parametrize(
        "day_offset,expected",
        # anchor 2026-04-15; interval 3 → due on multiples of 3
        [(d, (d % 3 == 0)) for d in range(-10, 11)],
    )
    def test_interval_negative_offsets_from_anchor(self, _is_due, day_offset, expected):
        """Python's `(task_date - anchor).days % interval` handles negatives
        by floor-div semantics — verify same-day and past-anchor dates still
        match correctly."""
        anchor = date(2026, 4, 15)
        sched = {"type": "interval", "interval_days": 3, "interval_anchor": "2026-04-15"}
        assert _is_due(_med_stub(sched), anchor + timedelta(days=day_offset)) is expected

    @pytest.mark.parametrize(
        "sched",
        [
            {},  # totally empty
            {"type": "weekly"},  # missing days_of_week → default all 7
            {"type": "interval"},  # missing both
            {"type": "interval", "interval_days": 2},  # missing anchor
            {"type": "interval", "interval_anchor": "2026-04-10"},  # missing interval_days
            {"type": "custom"},  # unknown type
            {"type": "interval", "interval_days": 0, "interval_anchor": "2026-04-10"},  # degenerate
            {"type": "foobar", "days_of_week": [0]},  # unknown type but has days
        ],
    )
    def test_malformed_schedules_safe_default_true(self, _is_due, sched):
        """Malformed schedule shapes must default to True (don't silently skip meds)."""
        assert _is_due(_med_stub(sched), date(2026, 4, 15)) is True

    def test_interval_one_day_is_daily(self, _is_due):
        sched = {"type": "interval", "interval_days": 1, "interval_anchor": "2026-04-10"}
        for d in range(1, 20):
            assert _is_due(_med_stub(sched), date(2026, 4, d)) is True

    def test_interval_seven_day_weekly_equivalent(self, _is_due):
        sched = {"type": "interval", "interval_days": 7, "interval_anchor": "2026-04-15"}
        assert _is_due(_med_stub(sched), date(2026, 4, 15)) is True   # 0
        assert _is_due(_med_stub(sched), date(2026, 4, 22)) is True   # +7
        assert _is_due(_med_stub(sched), date(2026, 4, 29)) is True   # +14
        for d in (16, 17, 18, 19, 20, 21):
            assert _is_due(_med_stub(sched), date(2026, 4, d)) is False

    def test_weekly_with_single_day_non_monday(self, _is_due):
        # Days: Mon=0, Tue=1, Wed=2, Thu=3, Fri=4, Sat=5, Sun=6
        # 2026-04-19 is Sunday (weekday=6)
        sched = {"type": "weekly", "days_of_week": [6]}
        assert _is_due(_med_stub(sched), date(2026, 4, 19)) is True
        assert _is_due(_med_stub(sched), date(2026, 4, 18)) is False  # Sat

    def test_weekly_full_week_enumeration(self, _is_due):
        """Matrix: for each subset of {Mon,Wed,Fri}, iterate all 7 weekdays."""
        # 2026-04-13 is Monday
        cases = [
            ([0], {0}),
            ([2], {2}),
            ([4], {4}),
            ([0, 4], {0, 4}),
            ([0, 2, 4], {0, 2, 4}),
        ]
        monday = date(2026, 4, 13)
        for days, expected_weekdays in cases:
            sched = {"type": "weekly", "days_of_week": days}
            for offset in range(7):
                d = monday + timedelta(days=offset)
                assert (
                    _is_due(_med_stub(sched), d) is (offset in expected_weekdays)
                ), f"days={days} offset={offset}"


# ── Pydantic schema validator permutations ──────────────────────────────────


class TestMedicationScheduleValidator:
    @pytest.mark.parametrize(
        "kwargs",
        [
            # weekly: empty days rejected
            {"type": "weekly", "days_of_week": []},
            # interval missing days
            {"type": "interval"},
            # interval with 0 days
            {"type": "interval", "interval_days": 0, "interval_anchor": date(2026, 4, 10)},
            # interval with negative days
            {"type": "interval", "interval_days": -1, "interval_anchor": date(2026, 4, 10)},
            # interval missing anchor
            {"type": "interval", "interval_days": 2},
        ],
    )
    def test_invalid_schedules_raise(self, kwargs):
        with pytest.raises(ValueError):
            MedicationSchedule(**kwargs)

    @pytest.mark.parametrize(
        "kwargs,expected_days",
        [
            # defaults
            ({}, [0, 1, 2, 3, 4, 5, 6]),
            # single day
            ({"days_of_week": [0]}, [0]),
            # all days explicit
            ({"days_of_week": [0, 1, 2, 3, 4, 5, 6]}, [0, 1, 2, 3, 4, 5, 6]),
            # only weekends
            ({"days_of_week": [5, 6]}, [5, 6]),
        ],
    )
    def test_valid_weekly(self, kwargs, expected_days):
        sched = MedicationSchedule(type="weekly", **kwargs)
        assert sched.days_of_week == expected_days

    @pytest.mark.parametrize("days", [7, 8, -1, 100])
    def test_invalid_day_of_week_values_rejected(self, days):
        with pytest.raises(ValueError):
            MedicationSchedule(type="weekly", days_of_week=[days])

    @pytest.mark.parametrize("interval", [1, 2, 7, 14, 30, 365])
    def test_valid_intervals_accepted(self, interval):
        sched = MedicationSchedule(
            type="interval", interval_days=interval, interval_anchor=date(2026, 4, 10),
        )
        assert sched.interval_days == interval


class TestMedicationDoseValidator:
    @pytest.mark.parametrize(
        "slot,quantity,should_pass",
        [
            ("morning", 1, True),
            ("afternoon", 1, True),
            ("evening", 1, True),
            ("night", 1, True),
            ("morning", 0.5, True),        # half tablet
            ("morning", 0.25, True),       # quarter
            ("morning", 1.5, True),        # odd float
            ("morning", 10, True),         # large but valid
            ("morning", 0, True),          # zero — schema doesn't constrain (documented behavior)
            ("morning", -1, True),         # schema doesn't constrain negative (documented behavior)
            # invalid slots
            ("MORNING", 1, False),
            ("", 1, False),
            ("late_night", 1, False),
            ("noon", 1, False),
            (None, 1, False),
        ],
    )
    def test_slot_and_quantity(self, slot, quantity, should_pass):
        if should_pass:
            d = MedicationDose(slot=slot, quantity=quantity)
            assert d.slot == slot
            assert d.quantity == quantity
        else:
            with pytest.raises(ValueError):
                MedicationDose(slot=slot, quantity=quantity)


class TestConfirmedMedicineValidator:
    def test_end_before_start_rejected(self):
        with pytest.raises(ValueError, match="end_date must be on or after start_date"):
            ConfirmedMedicine(
                name="Test",
                start_date=date(2026, 5, 1),
                end_date=date(2026, 4, 30),
            )

    @pytest.mark.parametrize(
        "start,end",
        [
            (date(2026, 5, 1), date(2026, 5, 1)),   # same day
            (date(2026, 5, 1), date(2026, 5, 2)),   # next day
            (date(2026, 5, 1), date(2027, 5, 1)),   # one year
            (date(2026, 5, 1), None),                # open-ended
        ],
    )
    def test_valid_date_ranges(self, start, end):
        med = ConfirmedMedicine(name="Test", start_date=start, end_date=end)
        assert med.start_date == start
        assert med.end_date == end

    def test_name_required(self):
        with pytest.raises(ValueError):
            ConfirmedMedicine(start_date=date.today())

    @pytest.mark.parametrize(
        "name",
        [
            "Metformin",
            "metformin",
            "METFORMIN",
            "Metformin HCl",
            "Paracetamol 500mg",
            "  Aspirin  ",   # whitespace preserved by schema
            "दवा",            # Hindi
            "دواء",           # Arabic
            "薬",              # Japanese
        ],
    )
    def test_name_accepts_unicode_and_whitespace(self, name):
        med = ConfirmedMedicine(name=name, start_date=date.today())
        assert med.name == name

    def test_optional_fields_default_to_none(self):
        med = ConfirmedMedicine(name="Test", start_date=date.today())
        assert med.brand_name is None
        assert med.strength is None
        assert med.formulation is None
        assert med.route is None
        assert med.food_timing is None
        assert med.purpose is None
        assert med.instructions is None
        assert med.doses == []
        assert med.schedule is None
        assert med.end_date is None
        assert med.is_sos is False

    def test_full_population(self):
        med = ConfirmedMedicine(
            name="Metformin",
            brand_name="Glucophage",
            strength="500mg",
            formulation="tablet",
            route="oral",
            food_timing="after food",
            purpose="diabetes",
            instructions="Take with water",
            doses=[
                MedicationDose(slot="morning", quantity=1),
                MedicationDose(slot="evening", quantity=1),
            ],
            schedule=MedicationSchedule(type="weekly", days_of_week=[0, 2, 4]),
            start_date=date(2026, 4, 15),
            end_date=date(2026, 5, 15),
            is_sos=False,
        )
        assert med.name == "Metformin"
        assert len(med.doses) == 2
        assert med.schedule.days_of_week == [0, 2, 4]


# ── to_response days_remaining matrix ───────────────────────────────────────


class TestToResponseDaysRemaining:
    """Locks the days_remaining calculation semantics across lifecycle states."""

    def _med(self, **overrides):
        from uuid import uuid4

        defaults = {
            "medication_id": uuid4(),
            "prescription_id": None,
            "name": "Test",
            "brand_name": None,
            "strength": None,
            "formulation": None,
            "route": None,
            "food_timing": None,
            "purpose": None,
            "instructions": None,
            "doses": [],
            "schedule": None,
            "start_date": TODAY,
            "end_date": None,
            "status": "active",
            "created_at": None,
        }
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    @pytest.mark.parametrize(
        "status,end_date,expected",
        [
            # active + end_date → days_remaining set
            ("active", TODAY, 0),
            ("active", TODAY + timedelta(days=1), 1),
            ("active", TODAY + timedelta(days=7), 7),
            ("active", TODAY + timedelta(days=365), 365),
            # already expired (end in past) clamped to 0
            ("active", TODAY - timedelta(days=1), 0),
            ("active", TODAY - timedelta(days=365), 0),
            # active without end → None
            ("active", None, None),
            # non-active statuses → None regardless
            ("paused", TODAY + timedelta(days=5), None),
            ("scheduled", TODAY + timedelta(days=5), None),
            ("as_needed", TODAY + timedelta(days=5), None),
            ("completed", TODAY + timedelta(days=5), None),
            ("discontinued", TODAY + timedelta(days=5), None),
        ],
    )
    def test_days_remaining(self, status, end_date, expected):
        med = self._med(status=status, end_date=end_date, created_at=None)
        # created_at required by MedicationResponse but we're only asserting days_remaining
        from datetime import datetime

        med.created_at = datetime(2026, 1, 1)
        resp = MedicationService.to_response(med, TODAY)
        assert resp.days_remaining == expected
        # is_sos derived strictly from status == 'as_needed'
        assert resp.is_sos == (status == "as_needed")
