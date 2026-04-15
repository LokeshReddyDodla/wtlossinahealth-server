"""Tests for medication scheduling — _is_medication_due and task generation."""

import importlib
import sys
from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest

from tests.gamification.helpers import (
    FakeScalarResult,
    FakeSession,
    base_stubs,
    load_module,
    make_module,
    model_class,
)


def _med(schedule=None, name="TestMed", strength="500mg", status="active",
         start_date=date(2026, 1, 1), end_date=None, doses=None):
    """Create a fake medication object."""
    return SimpleNamespace(
        medication_id=uuid4(),
        patient_id=uuid4(),
        name=name,
        strength=strength,
        status=status,
        schedule=schedule,
        start_date=start_date,
        end_date=end_date,
        doses=doses or [{"slot": "morning", "quantity": 1}],
    )


def _load_task_gen(monkeypatch):
    """Load the task generator module with mocks."""
    PatientMedication = model_class(
        "PatientMedication",
        "patient_id", "status", "start_date", "end_date", "medication_id",
        "schedule", "doses", "name", "strength",
    )
    PatientPrescription = model_class(
        "PatientPrescription",
        "patient_id", "status", "follow_up_required", "follow_up_date",
        "prescription_id", "doctor_name",
    )
    stubs = base_stubs()
    stubs["lib.models.patient_medication"] = make_module(
        "lib.models.patient_medication", PatientMedication=PatientMedication,
    )
    stubs["lib.models.patient_prescription"] = make_module(
        "lib.models.patient_prescription", PatientPrescription=PatientPrescription,
    )
    return load_module(
        monkeypatch,
        "lib/services/gamification/task_generator.py",
        "test_task_gen_sched",
        extra_stubs=stubs,
    )


# ── _is_medication_due ──────────────────────────────────────────────────


class TestIsMedicationDue:
    def _check(self, monkeypatch, schedule, task_date):
        module = _load_task_gen(monkeypatch)
        med = _med(schedule=schedule)
        return module.TaskGeneratorService._is_medication_due(med, task_date)

    def test_null_schedule_is_daily(self, monkeypatch):
        assert self._check(monkeypatch, None, date(2026, 4, 14)) is True
        assert self._check(monkeypatch, None, date(2026, 4, 15)) is True

    def test_weekly_monday_only(self, monkeypatch):
        # 2026-04-13 is Monday (weekday=0), 2026-04-14 is Tuesday
        assert self._check(monkeypatch, {"type": "weekly", "days_of_week": [0]}, date(2026, 4, 13)) is True
        assert self._check(monkeypatch, {"type": "weekly", "days_of_week": [0]}, date(2026, 4, 14)) is False

    def test_weekly_mwf(self, monkeypatch):
        sched = {"type": "weekly", "days_of_week": [0, 2, 4]}
        assert self._check(monkeypatch, sched, date(2026, 4, 13)) is True   # Mon
        assert self._check(monkeypatch, sched, date(2026, 4, 14)) is False  # Tue
        assert self._check(monkeypatch, sched, date(2026, 4, 15)) is True   # Wed
        assert self._check(monkeypatch, sched, date(2026, 4, 16)) is False  # Thu
        assert self._check(monkeypatch, sched, date(2026, 4, 17)) is True   # Fri

    def test_weekly_weekends(self, monkeypatch):
        sched = {"type": "weekly", "days_of_week": [5, 6]}
        assert self._check(monkeypatch, sched, date(2026, 4, 13)) is False  # Mon
        assert self._check(monkeypatch, sched, date(2026, 4, 18)) is True   # Sat
        assert self._check(monkeypatch, sched, date(2026, 4, 19)) is True   # Sun

    def test_weekly_all_seven_days(self, monkeypatch):
        sched = {"type": "weekly", "days_of_week": [0, 1, 2, 3, 4, 5, 6]}
        for day in range(13, 20):  # Mon-Sun
            assert self._check(monkeypatch, sched, date(2026, 4, day)) is True

    def test_interval_every_2_days(self, monkeypatch):
        sched = {"type": "interval", "interval_days": 2, "interval_anchor": "2026-04-10"}
        assert self._check(monkeypatch, sched, date(2026, 4, 10)) is True   # anchor
        assert self._check(monkeypatch, sched, date(2026, 4, 11)) is False
        assert self._check(monkeypatch, sched, date(2026, 4, 12)) is True
        assert self._check(monkeypatch, sched, date(2026, 4, 13)) is False
        assert self._check(monkeypatch, sched, date(2026, 4, 14)) is True

    def test_interval_every_3_days(self, monkeypatch):
        sched = {"type": "interval", "interval_days": 3, "interval_anchor": "2026-04-10"}
        assert self._check(monkeypatch, sched, date(2026, 4, 10)) is True
        assert self._check(monkeypatch, sched, date(2026, 4, 11)) is False
        assert self._check(monkeypatch, sched, date(2026, 4, 12)) is False
        assert self._check(monkeypatch, sched, date(2026, 4, 13)) is True
        assert self._check(monkeypatch, sched, date(2026, 4, 16)) is True

    def test_interval_malformed_no_anchor(self, monkeypatch):
        sched = {"type": "interval", "interval_days": 2}
        assert self._check(monkeypatch, sched, date(2026, 4, 14)) is True  # safe default

    def test_interval_malformed_no_interval_days(self, monkeypatch):
        sched = {"type": "interval", "interval_anchor": "2026-04-10"}
        assert self._check(monkeypatch, sched, date(2026, 4, 14)) is True  # safe default

    def test_unknown_schedule_type(self, monkeypatch):
        sched = {"type": "cyclical", "days_on": 21, "days_off": 7}
        assert self._check(monkeypatch, sched, date(2026, 4, 14)) is True  # safe default

    def test_weekly_defaults_to_all_days_if_missing(self, monkeypatch):
        sched = {"type": "weekly"}  # no days_of_week key
        assert self._check(monkeypatch, sched, date(2026, 4, 14)) is True


# ── Task description schedule awareness ─────────────────────────────────


class TestTaskDescriptionSchedule:
    """Verify task descriptions include schedule context."""

    @pytest.mark.asyncio
    async def test_daily_med_no_schedule_tag(self, monkeypatch):
        module = _load_task_gen(monkeypatch)
        service = module.TaskGeneratorService(postgres_store=None)

        meds = [_med(name="Metformin", strength="500mg", schedule=None)]
        session = FakeSession(results=[FakeScalarResult(values=meds)])

        tasks = await service._medication_tasks(uuid4(), date(2026, 4, 14), session)
        assert len(tasks) == 1
        assert "Metformin 500mg" in tasks[0].description
        assert "(weekly)" not in tasks[0].description

    @pytest.mark.asyncio
    async def test_weekly_med_has_tag(self, monkeypatch):
        module = _load_task_gen(monkeypatch)
        service = module.TaskGeneratorService(postgres_store=None)

        sched = {"type": "weekly", "days_of_week": [0]}
        meds = [_med(name="Methotrexate", strength="15mg", schedule=sched)]
        session = FakeSession(results=[FakeScalarResult(values=meds)])

        # Monday — med is due
        tasks = await service._medication_tasks(uuid4(), date(2026, 4, 13), session)
        assert len(tasks) == 1
        assert "(weekly)" in tasks[0].description

    @pytest.mark.asyncio
    async def test_3x_week_med_tag(self, monkeypatch):
        module = _load_task_gen(monkeypatch)
        service = module.TaskGeneratorService(postgres_store=None)

        sched = {"type": "weekly", "days_of_week": [0, 2, 4]}
        meds = [_med(name="VitD", strength="1000IU", schedule=sched)]
        session = FakeSession(results=[FakeScalarResult(values=meds)])

        tasks = await service._medication_tasks(uuid4(), date(2026, 4, 13), session)
        assert "(3x/week)" in tasks[0].description

    @pytest.mark.asyncio
    async def test_alternate_day_tag(self, monkeypatch):
        module = _load_task_gen(monkeypatch)
        service = module.TaskGeneratorService(postgres_store=None)

        sched = {"type": "interval", "interval_days": 2, "interval_anchor": "2026-04-13"}
        meds = [_med(name="Aspirin", strength="81mg", schedule=sched)]
        session = FakeSession(results=[FakeScalarResult(values=meds)])

        tasks = await service._medication_tasks(uuid4(), date(2026, 4, 13), session)
        assert "(alternate days)" in tasks[0].description

    @pytest.mark.asyncio
    async def test_every_3_days_tag(self, monkeypatch):
        module = _load_task_gen(monkeypatch)
        service = module.TaskGeneratorService(postgres_store=None)

        sched = {"type": "interval", "interval_days": 3, "interval_anchor": "2026-04-13"}
        meds = [_med(name="Iron", strength="325mg", schedule=sched)]
        session = FakeSession(results=[FakeScalarResult(values=meds)])

        tasks = await service._medication_tasks(uuid4(), date(2026, 4, 13), session)
        assert "(every 3 days)" in tasks[0].description

    @pytest.mark.asyncio
    async def test_weekly_med_not_due_generates_no_tasks(self, monkeypatch):
        module = _load_task_gen(monkeypatch)
        service = module.TaskGeneratorService(postgres_store=None)

        sched = {"type": "weekly", "days_of_week": [0]}  # Monday only
        meds = [_med(name="Methotrexate", schedule=sched)]
        session = FakeSession(results=[FakeScalarResult(values=meds)])

        # Tuesday — med is NOT due
        tasks = await service._medication_tasks(uuid4(), date(2026, 4, 14), session)
        assert len(tasks) == 0

    @pytest.mark.asyncio
    async def test_mixed_daily_and_weekly_on_non_scheduled_day(self, monkeypatch):
        module = _load_task_gen(monkeypatch)
        service = module.TaskGeneratorService(postgres_store=None)

        daily_med = _med(name="Metformin", strength="500mg", schedule=None)
        weekly_med = _med(name="Methotrexate", strength="15mg",
                          schedule={"type": "weekly", "days_of_week": [0]})  # Mon only
        meds = [daily_med, weekly_med]
        session = FakeSession(results=[FakeScalarResult(values=meds)])

        # Tuesday — only daily med is due
        tasks = await service._medication_tasks(uuid4(), date(2026, 4, 14), session)
        assert len(tasks) == 1
        assert "Metformin" in tasks[0].description
        assert "Methotrexate" not in tasks[0].description

    @pytest.mark.asyncio
    async def test_multiple_slots_generate_separate_tasks(self, monkeypatch):
        module = _load_task_gen(monkeypatch)
        service = module.TaskGeneratorService(postgres_store=None)

        med = _med(
            name="Metformin", strength="500mg",
            doses=[{"slot": "morning", "quantity": 1}, {"slot": "evening", "quantity": 0.5}],
        )
        session = FakeSession(results=[FakeScalarResult(values=[med])])

        tasks = await service._medication_tasks(uuid4(), date(2026, 4, 14), session)
        assert len(tasks) == 2
        task_types = {t.task_type for t in tasks}
        assert "TAKE_MEDICATION_MORNING" in task_types
        assert "TAKE_MEDICATION_EVENING" in task_types
