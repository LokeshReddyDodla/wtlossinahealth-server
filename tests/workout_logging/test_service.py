"""Unit tests for PatientWorkoutService CRUD.

We use the real SQLAlchemy models but mock the session. Side effects
(vector enqueue + gamification hook) are monkeypatched so we assert they
fire without invoking real Redis / container.
"""
from __future__ import annotations

from datetime import date, time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from lib.schemas.patient_workout import (
    PatientWorkoutCreate,
    PatientWorkoutExerciseInput,
    PatientWorkoutUpdate,
)
from lib.services.patient_workout_service import PatientWorkoutService
from tests.workout_logging.conftest import FakeResult, FakeSession


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_service(monkeypatch, postgres_store=None):
    """Instantiate service with side-effects neutered. Returns (service, trackers)."""
    service = PatientWorkoutService(postgres_store=postgres_store or SimpleNamespace())
    trackers = SimpleNamespace(
        vector_calls=[],
        gamification_calls=[],
    )

    def _track_vector(patient_id, response):
        trackers.vector_calls.append((patient_id, response))

    async def _track_gamification(patient_id):
        trackers.gamification_calls.append(patient_id)

    monkeypatch.setattr(service, "_fire_vector", _track_vector)
    monkeypatch.setattr(service, "_fire_gamification", _track_gamification)
    return service, trackers


def _catalog_result(catalog_row_factory, ids_and_names):
    return FakeResult(rows=[catalog_row_factory(i, n) for i, n in ids_and_names])


# ── create ────────────────────────────────────────────────────────────────────


class TestCreate:
    @pytest.mark.asyncio
    async def test_happy_path_strength_session(
        self, monkeypatch, patient_id, catalog_row_factory
    ):
        service, trackers = _make_service(monkeypatch)
        session = FakeSession(
            results=[
                _catalog_result(
                    catalog_row_factory,
                    [("Bench_Press", "Barbell Bench Press"), ("Squat", "Back Squat")],
                ),
                lambda _q: FakeResult(scalar_one=session.added[0]),
            ]
        )
        data = PatientWorkoutCreate(
            date=date(2026, 4, 20),
            time=time(18, 30),
            type="strength",
            duration_minutes=55,
            intensity="vigorous",
            exercises=[
                PatientWorkoutExerciseInput(
                    exercise_id="Bench_Press", order_index=0, sets=3, reps=10, weight_kg=60.0
                ),
                PatientWorkoutExerciseInput(
                    exercise_id="Squat", order_index=1, sets=5, reps=5, weight_kg=100.0
                ),
            ],
        )

        response = await service.create(
            patient_id, data, postgres_session=session
        )

        assert response.date == date(2026, 4, 20)
        assert response.type == "strength"
        assert response.duration_minutes == 55
        assert len(response.exercises) == 2
        # Catalog name is denormalized into the line item, not the raw slug
        assert response.exercises[0].exercise_name == "Barbell Bench Press"
        assert response.exercises[1].exercise_name == "Back Squat"
        # Session behaviour
        assert session.commit_count == 1
        assert len(session.added) == 1
        assert len(session.refresh_calls) == 0
        # Side effects fired
        assert len(trackers.vector_calls) == 1
        assert trackers.gamification_calls == [patient_id]

    @pytest.mark.asyncio
    async def test_unknown_exercise_id_raises_404(
        self, monkeypatch, patient_id, catalog_row_factory
    ):
        from fastapi import HTTPException

        service, trackers = _make_service(monkeypatch)
        session = FakeSession(
            results=[_catalog_result(catalog_row_factory, [("Bench_Press", "Bench Press")])]
        )
        data = PatientWorkoutCreate(
            date=date(2026, 4, 20),
            type="strength",
            exercises=[
                PatientWorkoutExerciseInput(exercise_id="Bench_Press"),
                PatientWorkoutExerciseInput(exercise_id="Nonexistent_Exercise"),
            ],
        )

        with pytest.raises(HTTPException) as exc:
            await service.create(patient_id, data, postgres_session=session)

        assert exc.value.status_code == 404
        assert "Nonexistent_Exercise" in str(exc.value.detail)
        # Nothing should be committed, no side effects
        assert session.commit_count == 0
        assert len(session.added) == 0
        assert trackers.vector_calls == []
        assert trackers.gamification_calls == []

    @pytest.mark.asyncio
    async def test_empty_exercises_allowed_for_cardio(
        self, monkeypatch, patient_id
    ):
        """A 30-min run with no per-exercise detail is valid: just date+type+duration."""
        service, trackers = _make_service(monkeypatch)
        session = FakeSession(
            results=[lambda _q: FakeResult(scalar_one=session.added[0])]
        )

        data = PatientWorkoutCreate(
            date=date(2026, 4, 20),
            type="cardio",
            duration_minutes=30,
            exercises=[],
        )

        response = await service.create(patient_id, data, postgres_session=session)

        assert response.exercises == []
        assert response.duration_minutes == 30
        assert session.commit_count == 1
        assert len(trackers.vector_calls) == 1
        assert trackers.gamification_calls == [patient_id]

    @pytest.mark.asyncio
    async def test_duplicate_exercise_id_validated_once(
        self, monkeypatch, patient_id, catalog_row_factory
    ):
        """Two sets of bench press should only trigger one catalog lookup for that id."""
        service, _ = _make_service(monkeypatch)

        # Only ONE catalog result queued — proves _validate_catalog_ids dedupes ids
        session = FakeSession(
            results=[
                _catalog_result(catalog_row_factory, [("Bench_Press", "Bench Press")]),
                lambda _q: FakeResult(scalar_one=session.added[0]),
            ]
        )
        data = PatientWorkoutCreate(
            date=date(2026, 4, 20),
            type="strength",
            exercises=[
                PatientWorkoutExerciseInput(exercise_id="Bench_Press", order_index=0),
                PatientWorkoutExerciseInput(exercise_id="Bench_Press", order_index=1),
            ],
        )

        response = await service.create(patient_id, data, postgres_session=session)
        assert len(response.exercises) == 2
        assert all(ex.exercise_name == "Bench Press" for ex in response.exercises)

    @pytest.mark.asyncio
    async def test_source_and_plan_session_id_preserved(
        self, monkeypatch, patient_id
    ):
        service, _ = _make_service(monkeypatch)
        session = FakeSession(
            results=[lambda _q: FakeResult(scalar_one=session.added[0])]
        )
        plan_sess = uuid4()
        data = PatientWorkoutCreate(
            date=date(2026, 4, 20),
            type="strength",
            source="manual",
            fitness_plan_session_id=plan_sess,
        )

        response = await service.create(patient_id, data, postgres_session=session)
        assert response.source == "manual"
        assert response.fitness_plan_session_id == plan_sess


# ── get ───────────────────────────────────────────────────────────────────────


def _fake_segment(*, type_="strength", duration_minutes=55, exercises=None, order_index=0):
    """A stand-in for a PatientWorkoutSegment ORM row."""
    return SimpleNamespace(
        id=uuid4(),
        type=type_,
        duration_minutes=duration_minutes,
        order_index=order_index,
        exercises=exercises or [],
    )


def _fake_workout_row(workout_id, patient_id, *, exercises=None, segments=None):
    """A stand-in ORM row — uses SimpleNamespace so we don't hit the real
    relationship attrs (which need a session).

    If `exercises` is given without `segments`, auto-wraps them into a single
    default segment (mirrors the schema validator behaviour).
    """
    if segments is None:
        segments = [_fake_segment(exercises=exercises or [])]
    return SimpleNamespace(
        id=UUID(workout_id),
        patient_id=UUID(patient_id),
        date=date(2026, 4, 20),
        time=time(18, 30),
        intensity="vigorous",
        calories_burned=420.0,
        notes="felt good",
        image_url=None,
        source="app",
        fitness_plan_session_id=None,
        uploaded_at=None,
        segments=segments,
    )


def _fake_exercise_row(exercise_id="Bench_Press", name="Bench Press", set_details=None):
    return SimpleNamespace(
        id=uuid4(),
        exercise_id=exercise_id,
        exercise_name=name,
        order_index=0,
        sets=3,
        reps=10,
        weight_kg=60.0,
        duration_seconds=None,
        distance_m=None,
        notes=None,
        set_details=set_details or [],
    )


class TestGet:
    @pytest.mark.asyncio
    async def test_returns_response_when_found(
        self, monkeypatch, patient_id, workout_id
    ):
        service, _ = _make_service(monkeypatch)
        row = _fake_workout_row(
            workout_id, patient_id, exercises=[_fake_exercise_row()]
        )
        session = FakeSession(results=[FakeResult(scalar_one_or_none=row)])

        response = await service.get(
            patient_id, workout_id, postgres_session=session
        )
        assert response is not None
        assert str(response.id) == workout_id
        assert len(response.exercises) == 1
        assert response.exercises[0].exercise_name == "Bench Press"

    @pytest.mark.asyncio
    async def test_returns_none_when_missing(
        self, monkeypatch, patient_id, workout_id
    ):
        service, _ = _make_service(monkeypatch)
        session = FakeSession(results=[FakeResult(scalar_one_or_none=None)])

        response = await service.get(
            patient_id, workout_id, postgres_session=session
        )
        assert response is None


# ── list ──────────────────────────────────────────────────────────────────────


class TestList:
    @pytest.mark.asyncio
    async def test_defaults_to_last_30_days(
        self, monkeypatch, patient_id
    ):
        """When no dates are passed, service computes a 30-day window.
        Two queries are issued: count then rows."""
        service, _ = _make_service(monkeypatch)
        row = _fake_workout_row(str(uuid4()), patient_id)
        session = FakeSession(
            results=[
                FakeResult(scalar_one=1),
                FakeResult(rows=[row]),
            ]
        )

        response = await service.list(patient_id, postgres_session=session)
        assert response.total == 1
        assert response.limit == 20
        assert response.offset == 0
        assert len(response.items) == 1

    @pytest.mark.asyncio
    async def test_pagination_respects_limit_offset(
        self, monkeypatch, patient_id
    ):
        service, _ = _make_service(monkeypatch)
        rows = [_fake_workout_row(str(uuid4()), patient_id) for _ in range(5)]
        session = FakeSession(
            results=[FakeResult(scalar_one=50), FakeResult(rows=rows)]
        )

        response = await service.list(
            patient_id, limit=5, offset=10, postgres_session=session
        )
        assert response.total == 50
        assert response.limit == 5
        assert response.offset == 10
        assert len(response.items) == 5

    @pytest.mark.asyncio
    async def test_zero_total_returns_empty_list(
        self, monkeypatch, patient_id
    ):
        service, _ = _make_service(monkeypatch)
        session = FakeSession(
            results=[FakeResult(scalar_one=0), FakeResult(rows=[])]
        )

        response = await service.list(patient_id, postgres_session=session)
        assert response.total == 0
        assert response.items == []


# ── update ────────────────────────────────────────────────────────────────────


class TestUpdate:
    @pytest.mark.asyncio
    async def test_missing_workout_returns_none(
        self, monkeypatch, patient_id, workout_id
    ):
        service, _ = _make_service(monkeypatch)
        session = FakeSession(results=[FakeResult(scalar_one_or_none=None)])

        response = await service.update(
            patient_id,
            workout_id,
            PatientWorkoutUpdate(notes="new"),
            postgres_session=session,
        )
        assert response is None

    @pytest.mark.asyncio
    async def test_partial_update_without_replacing_exercises(
        self, monkeypatch, patient_id, workout_id
    ):
        service, trackers = _make_service(monkeypatch)
        existing = _fake_workout_row(
            workout_id, patient_id,
            segments=[_fake_segment(exercises=[_fake_exercise_row()])],
        )
        session = FakeSession(results=[
            FakeResult(scalar_one_or_none=existing),
            FakeResult(scalar_one=existing),
        ])

        response = await service.update(
            patient_id,
            workout_id,
            PatientWorkoutUpdate(notes="changed", intensity="light"),
            postgres_session=session,
        )
        assert response is not None
        assert existing.notes == "changed"
        assert existing.intensity == "light"
        # Exercises untouched
        assert len(response.exercises) == 1
        # commit happened once
        assert session.commit_count == 1
        # Vector re-fires on update
        assert len(trackers.vector_calls) == 1

    @pytest.mark.asyncio
    async def test_exercises_replacement_deletes_old_and_adds_new(
        self, monkeypatch, patient_id, workout_id, catalog_row_factory
    ):
        service, _ = _make_service(monkeypatch)
        old_ex = _fake_exercise_row()
        old_seg = _fake_segment(exercises=[old_ex])
        existing = _fake_workout_row(workout_id, patient_id, segments=[old_seg])
        # Queries in order: fetch workout, validate catalog ids, re-query after commit
        session = FakeSession(
            results=[
                FakeResult(scalar_one_or_none=existing),
                _catalog_result(catalog_row_factory, [("Deadlift", "Deadlift")]),
                FakeResult(scalar_one=existing),
            ]
        )

        response = await service.update(
            patient_id,
            workout_id,
            PatientWorkoutUpdate(
                exercises=[
                    PatientWorkoutExerciseInput(
                        exercise_id="Deadlift", order_index=0, sets=3, reps=5
                    )
                ]
            ),
            postgres_session=session,
        )

        assert response is not None
        # Old segment deleted (service deletes segments, which cascades)
        assert old_seg in session.deleted
        # New exercise present in the new segment
        all_exercises = [
            ex for seg in existing.segments for ex in seg.exercises
        ]
        new_names = [ex.exercise_name for ex in all_exercises]
        assert "Deadlift" in new_names
        assert session.commit_count == 1

    @pytest.mark.asyncio
    async def test_update_with_unknown_exercise_id_raises_404(
        self, monkeypatch, patient_id, workout_id, catalog_row_factory
    ):
        from fastapi import HTTPException

        service, _ = _make_service(monkeypatch)
        existing = _fake_workout_row(workout_id, patient_id, segments=[_fake_segment(exercises=[])])
        session = FakeSession(
            results=[
                FakeResult(scalar_one_or_none=existing),
                # Catalog returns nothing → "Bogus" will be flagged missing
                _catalog_result(catalog_row_factory, []),
            ]
        )
        with pytest.raises(HTTPException) as exc:
            await service.update(
                patient_id,
                workout_id,
                PatientWorkoutUpdate(
                    exercises=[PatientWorkoutExerciseInput(exercise_id="Bogus")]
                ),
                postgres_session=session,
            )
        assert exc.value.status_code == 404


# ── delete ────────────────────────────────────────────────────────────────────


class TestDelete:
    @pytest.mark.asyncio
    async def test_deletes_and_removes_vector(
        self, monkeypatch, patient_id, workout_id
    ):
        service, _ = _make_service(monkeypatch)
        row = _fake_workout_row(workout_id, patient_id)
        session = FakeSession(results=[FakeResult(scalar_one_or_none=row)])

        delete_calls = []

        class _FakeVectorService:
            async def delete_workout_vector(self, wid):
                delete_calls.append(wid)

        from lib.core import container as container_mod
        from lib.services.vector import WorkoutVectorService

        original_resolve = container_mod.container.resolve

        def _fake_resolve(cls):
            if cls is WorkoutVectorService:
                return _FakeVectorService()
            return original_resolve(cls)

        monkeypatch.setattr(container_mod.container, "resolve", _fake_resolve)

        ok = await service.delete(patient_id, workout_id, postgres_session=session)

        assert ok is True
        assert row in session.deleted
        assert session.commit_count == 1
        assert delete_calls == [workout_id]

    @pytest.mark.asyncio
    async def test_vector_cleanup_failure_does_not_block_delete(
        self, monkeypatch, patient_id, workout_id
    ):
        """If the Qdrant vector cleanup throws, the DB delete still succeeds —
        logs the warning and returns True."""
        service, _ = _make_service(monkeypatch)
        row = _fake_workout_row(workout_id, patient_id)
        session = FakeSession(results=[FakeResult(scalar_one_or_none=row)])

        class _BrokenVectorService:
            async def delete_workout_vector(self, _wid):
                raise RuntimeError("qdrant down")

        from lib.core import container as container_mod
        from lib.services.vector import WorkoutVectorService

        original_resolve = container_mod.container.resolve

        def _fake_resolve(cls):
            if cls is WorkoutVectorService:
                return _BrokenVectorService()
            return original_resolve(cls)

        monkeypatch.setattr(container_mod.container, "resolve", _fake_resolve)

        ok = await service.delete(patient_id, workout_id, postgres_session=session)
        assert ok is True
        assert session.commit_count == 1

    @pytest.mark.asyncio
    async def test_missing_workout_returns_false(
        self, monkeypatch, patient_id, workout_id
    ):
        service, _ = _make_service(monkeypatch)
        session = FakeSession(results=[FakeResult(scalar_one_or_none=None)])

        ok = await service.delete(patient_id, workout_id, postgres_session=session)
        assert ok is False
        assert session.commit_count == 0


# ── Side-effect isolation ─────────────────────────────────────────────────────


class TestSideEffectsDoNotBreakCommit:
    """The inner enqueue + gamification calls are wrapped in try/except inside
    _fire_vector and _fire_gamification. If either fails, create() must still
    commit and return the response. We simulate failures by patching the
    module-level symbols those helpers import."""

    @pytest.mark.asyncio
    async def test_vector_enqueue_failure_does_not_block_create(
        self, monkeypatch, patient_id
    ):
        service = PatientWorkoutService(postgres_store=SimpleNamespace())

        # Real _fire_vector runs, but its inner import raises on call
        import lib.workers.tasks.workout.enqueue as enqueue_mod

        def _broken(*_args, **_kwargs):
            raise RuntimeError("redis down")

        monkeypatch.setattr(
            enqueue_mod, "enqueue_generate_workout_vector_sync", _broken
        )

        async def _ok_game(_pid):
            return None

        monkeypatch.setattr(service, "_fire_gamification", _ok_game)
        session = FakeSession(
            results=[lambda _q: FakeResult(scalar_one=session.added[0])]
        )
        data = PatientWorkoutCreate(
            date=date(2026, 4, 20), type="cardio", duration_minutes=30
        )

        response = await service.create(
            patient_id, data, postgres_session=session
        )
        assert response.type == "cardio"
        assert session.commit_count == 1

    @pytest.mark.asyncio
    async def test_gamification_failure_does_not_block_create(
        self, monkeypatch, patient_id
    ):
        service = PatientWorkoutService(postgres_store=SimpleNamespace())

        # Neutralize vector to isolate gamification path
        monkeypatch.setattr(service, "_fire_vector", lambda *a, **k: None)

        # Force gamification hook to raise; the helper's try/except should swallow it
        from lib.core import container as container_mod

        class _BrokenHandler:
            async def on_fitness_synced(self, *args, **kwargs):
                raise RuntimeError("gamification bug")

        original_resolve = container_mod.container.resolve

        def _fake_resolve(cls):
            from lib.services.gamification.event_handler import (
                GamificationEventHandler,
            )
            if cls is GamificationEventHandler:
                return _BrokenHandler()
            return original_resolve(cls)

        monkeypatch.setattr(container_mod.container, "resolve", _fake_resolve)

        session = FakeSession(
            results=[lambda _q: FakeResult(scalar_one=session.added[0])]
        )
        data = PatientWorkoutCreate(
            date=date(2026, 4, 20), type="cardio", duration_minutes=30
        )

        response = await service.create(
            patient_id, data, postgres_session=session
        )
        assert response.type == "cardio"
        assert session.commit_count == 1
