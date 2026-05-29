"""Pass-6 gap-coverage tests.

These catch corners not directly covered by the per-module test files:
- patient-scoping on get/delete (can't see other patients' workouts)
- order_index round-trips through create
- update clearing all exercises with empty list
- update only touching specific fields preserves others
- SQLAlchemyError during create is surfaced as 500
- ordering: commit precedes vector cleanup on delete
"""
from __future__ import annotations

from datetime import date, time
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from lib.schemas.patient_workout import (
    PatientWorkoutCreate,
    PatientWorkoutExerciseInput,
    PatientWorkoutUpdate,
)
from lib.services.patient_workout_service import PatientWorkoutService
from tests.workout_logging.conftest import FakeResult, FakeSession


def _make_service(monkeypatch):
    service = PatientWorkoutService(postgres_store=SimpleNamespace())
    monkeypatch.setattr(service, "_fire_vector", lambda *a, **k: None)

    async def _noop(_pid):
        return None

    monkeypatch.setattr(service, "_fire_gamification", _noop)
    return service


def _catalog_row(id_, name):
    return SimpleNamespace(id=id_, name=name)


# ── Patient scoping ──────────────────────────────────────────────────────────


class TestPatientScoping:
    @pytest.mark.asyncio
    async def test_get_returns_none_for_wrong_patient(
        self, monkeypatch, patient_id, another_patient_id, workout_id
    ):
        """If the workout belongs to a different patient, the WHERE clause
        filters it out and get() returns None. We emulate that by queuing None."""
        service = _make_service(monkeypatch)
        session = FakeSession(results=[FakeResult(scalar_one_or_none=None)])

        response = await service.get(
            another_patient_id, workout_id, postgres_session=session
        )
        assert response is None

    @pytest.mark.asyncio
    async def test_delete_returns_false_for_wrong_patient(
        self, monkeypatch, another_patient_id, workout_id
    ):
        service = _make_service(monkeypatch)
        session = FakeSession(results=[FakeResult(scalar_one_or_none=None)])
        ok = await service.delete(
            another_patient_id, workout_id, postgres_session=session
        )
        assert ok is False


# ── Exercise order preservation ──────────────────────────────────────────────


class TestExerciseOrder:
    @pytest.mark.asyncio
    async def test_order_index_round_trips(
        self, monkeypatch, patient_id
    ):
        service = _make_service(monkeypatch)
        session = FakeSession(
            results=[
                FakeResult(rows=[_catalog_row("A", "A name"), _catalog_row("B", "B name")]),
                lambda _q: FakeResult(scalar_one=session.added[0]),
            ]
        )
        data = PatientWorkoutCreate(
            date=date(2026, 4, 20),
            type="strength",
            exercises=[
                PatientWorkoutExerciseInput(exercise_id="A", order_index=0),
                PatientWorkoutExerciseInput(exercise_id="B", order_index=1),
            ],
        )

        response = await service.create(patient_id, data, postgres_session=session)
        # Order preserved as provided
        assert [ex.order_index for ex in response.exercises] == [0, 1]
        assert [ex.exercise_id for ex in response.exercises] == ["A", "B"]


# ── Update edge cases ────────────────────────────────────────────────────────


def _fake_row_with_exercises(patient_id, workout_id, exercises):
    return SimpleNamespace(
        id=UUID(workout_id),
        patient_id=UUID(patient_id),
        date=date(2026, 4, 20),
        time=time(18, 30),
        type="strength",
        duration_minutes=55,
        intensity="vigorous",
        calories_burned=None,
        notes="original",
        image_url=None,
        source="app",
        fitness_plan_session_id=None,
        uploaded_at=None,
        exercises=list(exercises),
    )


class TestUpdateEdgeCases:
    @pytest.mark.asyncio
    async def test_empty_exercise_list_clears_all(
        self, monkeypatch, patient_id, workout_id
    ):
        service = _make_service(monkeypatch)
        old_ex = SimpleNamespace(
            id=uuid4(), exercise_id="X", exercise_name="X",
            order_index=0, sets=1, reps=1, weight_kg=1.0,
            duration_seconds=None, distance_m=None, notes=None,
        )
        existing = _fake_row_with_exercises(patient_id, workout_id, [old_ex])
        # Queries: fetch workout, validate (empty list → no query), re-query after commit
        session = FakeSession(results=[
            FakeResult(scalar_one_or_none=existing),
            FakeResult(scalar_one=existing),
        ])

        response = await service.update(
            patient_id, workout_id,
            PatientWorkoutUpdate(exercises=[]),
            postgres_session=session,
        )
        assert response is not None
        assert response.exercises == []
        assert old_ex in session.deleted

    @pytest.mark.asyncio
    async def test_partial_update_leaves_other_fields_alone(
        self, monkeypatch, patient_id, workout_id
    ):
        service = _make_service(monkeypatch)
        existing = _fake_row_with_exercises(patient_id, workout_id, [])
        session = FakeSession(results=[
            FakeResult(scalar_one_or_none=existing),
            FakeResult(scalar_one=existing),
        ])

        await service.update(
            patient_id, workout_id,
            PatientWorkoutUpdate(notes="updated notes"),
            postgres_session=session,
        )
        # Only `notes` changed; everything else untouched
        assert existing.notes == "updated notes"
        assert existing.type == "strength"
        assert existing.duration_minutes == 55
        assert existing.intensity == "vigorous"


# ── Error paths ──────────────────────────────────────────────────────────────


class TestErrorPaths:
    @pytest.mark.asyncio
    async def test_sqlalchemy_error_on_commit_raises_500(
        self, monkeypatch, patient_id
    ):
        from fastapi import HTTPException
        from sqlalchemy.exc import SQLAlchemyError

        service = _make_service(monkeypatch)
        session = FakeSession(results=[])

        async def _broken_commit():
            raise SQLAlchemyError("db exploded")

        session.commit = _broken_commit  # type: ignore[method-assign]

        data = PatientWorkoutCreate(
            date=date(2026, 4, 20), type="cardio", duration_minutes=30
        )

        with pytest.raises(HTTPException) as exc:
            await service.create(patient_id, data, postgres_session=session)
        assert exc.value.status_code == 500


# ── Delete ordering ──────────────────────────────────────────────────────────


class TestDeleteOrdering:
    @pytest.mark.asyncio
    async def test_commit_happens_before_vector_cleanup(
        self, monkeypatch, patient_id, workout_id
    ):
        """If the vector cleanup throws, the DB delete must have already
        committed — otherwise orphaned Qdrant points could be left behind.
        Verify ordering with a shared event log."""
        events: list[str] = []

        service = _make_service(monkeypatch)
        row = SimpleNamespace(
            id=UUID(workout_id),
            patient_id=UUID(patient_id),
            date=date(2026, 4, 25),
        )
        session = FakeSession(results=[FakeResult(scalar_one_or_none=row)])

        original_commit = session.commit

        async def _commit():
            events.append("commit")
            await original_commit()

        session.commit = _commit  # type: ignore[method-assign]

        class _VectorService:
            async def delete_workout_vector(self, _wid):
                events.append("vector_delete")

        from lib.core import container as container_mod
        from lib.services.vector import WorkoutVectorService

        original_resolve = container_mod.container.resolve

        def _fake_resolve(cls):
            if cls is WorkoutVectorService:
                return _VectorService()
            return original_resolve(cls)

        monkeypatch.setattr(container_mod.container, "resolve", _fake_resolve)

        await service.delete(patient_id, workout_id, postgres_session=session)
        assert events == ["commit", "vector_delete"]
