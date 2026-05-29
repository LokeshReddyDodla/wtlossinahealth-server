"""Unit tests for WorkoutVoiceService.

Covers the interpretation pipeline, exercise matching, session state
application, multi-exercise extraction, and edge cases.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Optional
from unittest.mock import AsyncMock

import pytest

from lib.schemas.exercise import ExerciseResponse
from lib.schemas.workout_voice import (
    ExerciseActionItem,
    ExerciseMatch,
    ParsedSet,
    SessionExercise,
    SetEntry,
    VoiceWorkoutExtraction,
    WorkoutVoiceSessionState,
)
from lib.services.workout_voice_service import (
    EmptyTranscriptError,
    WorkoutVoiceService,
    _MATCH_CONFIDENCE_THRESHOLD,
)
from tests.workout_logging.conftest import FakeResult, FakeSession


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_service(*, fake_postgres_store=None):
    gateway = AsyncMock()
    stt = AsyncMock()
    store = fake_postgres_store or SimpleNamespace(engine=SimpleNamespace(pool=None))
    return WorkoutVoiceService(gateway=gateway, stt=stt, postgres_store=store)


def _make_item(
    action="new_exercise",
    exercise_name="Barbell Bench Press",
    sets=None,
):
    return ExerciseActionItem(
        action=action,
        exercise_name=exercise_name,
        sets=sets or [],
    )


def _make_extraction(
    items=None,
    interpretation="Got it",
    *,
    action="new_exercise",
    exercise_name="Barbell Bench Press",
    sets=None,
):
    if items is not None:
        return VoiceWorkoutExtraction(items=items, interpretation=interpretation)
    return VoiceWorkoutExtraction(
        items=[_make_item(action=action, exercise_name=exercise_name, sets=sets or [])],
        interpretation=interpretation,
    )


def _make_match(
    exercise_id="barbell_bench_press",
    exercise_name="Barbell Bench Press",
    confidence=1.0,
):
    return ExerciseMatch(
        exercise_id=exercise_id,
        exercise_name=exercise_name,
        confidence=confidence,
    )


def _make_session(*exercises):
    return WorkoutVoiceSessionState(exercises=list(exercises))


def _make_session_exercise(name, sets=None):
    return SessionExercise(
        exercise_name=name,
        sets=sets or [],
    )


def _fake_exercise_row(id_="barbell_bench_press", name="Barbell Bench Press"):
    return SimpleNamespace(
        id=id_,
        name=name,
        force="push",
        level="intermediate",
        mechanic="compound",
        equipment="barbell",
        category="strength",
        primary_muscles=["chest"],
        secondary_muscles=["triceps"],
        instructions=["Lie on bench"],
        image_urls=[],
        search_tsv=None,
    )


# ── Constructor ──────────────────────────────────────────────────────────────


class TestConstructor:
    def test_postgres_store_attribute_exists(self):
        svc = _make_service()
        assert hasattr(svc, "postgres_store")

    def test_postgres_store_not_private(self):
        svc = _make_service()
        assert not hasattr(svc, "_postgres_store")


# ── _needs_confirmation ──────────────────────────────────────────────────────


class TestNeedsConfirmation:
    def test_finish_never_needs_confirmation(self):
        item = _make_item(action="finish")
        assert WorkoutVoiceService._needs_confirmation(item, _make_match()) is False

    def test_unclear_never_needs_confirmation(self):
        item = _make_item(action="unclear")
        assert WorkoutVoiceService._needs_confirmation(item, _make_match()) is False

    def test_remove_exercise_never_needs_confirmation(self):
        item = _make_item(action="remove_exercise")
        assert WorkoutVoiceService._needs_confirmation(item, _make_match()) is False

    def test_add_set_never_needs_confirmation(self):
        item = _make_item(action="add_set")
        assert WorkoutVoiceService._needs_confirmation(item, _make_match()) is False

    def test_update_last_set_never_needs_confirmation(self):
        item = _make_item(action="update_last_set")
        assert WorkoutVoiceService._needs_confirmation(item, _make_match()) is False

    def test_no_match_needs_confirmation(self):
        item = _make_item(action="new_exercise")
        assert WorkoutVoiceService._needs_confirmation(item, None) is True

    def test_low_confidence_needs_confirmation(self):
        item = _make_item(action="new_exercise")
        match = _make_match(confidence=0.6)
        assert WorkoutVoiceService._needs_confirmation(item, match) is True

    def test_high_confidence_does_not_need_confirmation(self):
        item = _make_item(action="new_exercise")
        match = _make_match(confidence=0.9)
        assert WorkoutVoiceService._needs_confirmation(item, match) is False

    def test_exact_threshold_does_not_need_confirmation(self):
        item = _make_item(action="new_exercise")
        match = _make_match(confidence=_MATCH_CONFIDENCE_THRESHOLD)
        assert WorkoutVoiceService._needs_confirmation(item, match) is False


# ── _find_exercise_index ─────────────────────────────────────────────────────


class TestFindExerciseIndex:
    def test_empty_exercises_returns_none(self):
        assert WorkoutVoiceService._find_exercise_index([], "Bench", "bench") is None

    def test_exact_match_by_matched_name(self):
        exercises = [
            _make_session_exercise("Back Squat"),
            _make_session_exercise("Barbell Bench Press"),
        ]
        idx = WorkoutVoiceService._find_exercise_index(
            exercises, "Barbell Bench Press", "bench"
        )
        assert idx == 1

    def test_exact_match_by_raw_name(self):
        exercises = [
            _make_session_exercise("bench"),
            _make_session_exercise("squat"),
        ]
        idx = WorkoutVoiceService._find_exercise_index(
            exercises, "Barbell Bench Press", "bench"
        )
        assert idx == 0

    def test_no_match_without_fallback_returns_none(self):
        exercises = [_make_session_exercise("Deadlift")]
        idx = WorkoutVoiceService._find_exercise_index(
            exercises, "Bench Press", "bench", fallback_to_last=False
        )
        assert idx is None

    def test_no_match_with_fallback_returns_last(self):
        exercises = [
            _make_session_exercise("Deadlift"),
            _make_session_exercise("Squat"),
        ]
        idx = WorkoutVoiceService._find_exercise_index(
            exercises, "Bench Press", "bench", fallback_to_last=True
        )
        assert idx == 1

    def test_case_insensitive(self):
        exercises = [_make_session_exercise("BARBELL BENCH PRESS")]
        idx = WorkoutVoiceService._find_exercise_index(
            exercises, "barbell bench press", None
        )
        assert idx == 0


# ── _apply_item ──────────────────────────────────────────────────────────────


class TestApplyItem:
    def _apply(self, session, item, match=None, candidates=None, interpretation="Got it"):
        svc = _make_service()
        return svc._apply_item(
            session=session,
            item=item,
            match=match,
            candidates=candidates or [],
            interpretation=interpretation,
        )

    def test_new_exercise_adds_to_session(self):
        session = _make_session()
        item = _make_item(
            action="new_exercise",
            exercise_name="Bench Press",
            sets=[ParsedSet(weight_kg=80, reps=10)],
        )
        match = _make_match(confidence=1.0)

        updated, update = self._apply(session, item, match)

        assert len(updated.exercises) == 1
        assert updated.exercises[0].exercise_name == "Barbell Bench Press"
        assert updated.exercises[0].exercise_id == "barbell_bench_press"
        assert len(updated.exercises[0].sets) == 1
        assert updated.exercises[0].sets[0].weight_kg == 80
        assert update.action == "new_exercise"
        assert update.exercise_index == 0

    def test_add_set_to_existing_exercise(self):
        existing = _make_session_exercise(
            "Barbell Bench Press",
            sets=[SetEntry(weight_kg=80, reps=10)],
        )
        session = _make_session(existing)
        item = _make_item(
            action="add_set",
            exercise_name="Barbell Bench Press",
            sets=[ParsedSet(weight_kg=80, reps=8)],
        )
        match = _make_match(confidence=1.0)

        updated, update = self._apply(session, item, match)

        assert len(updated.exercises) == 1
        assert len(updated.exercises[0].sets) == 2
        assert updated.exercises[0].sets[1].reps == 8
        assert update.action == "add_set"

    def test_add_set_fallback_to_last_exercise(self):
        ex1 = _make_session_exercise("Deadlift", [SetEntry(weight_kg=100, reps=5)])
        ex2 = _make_session_exercise("Squat", [SetEntry(weight_kg=80, reps=8)])
        session = _make_session(ex1, ex2)
        item = _make_item(
            action="add_set",
            exercise_name="Unknown Thing",
            sets=[ParsedSet(weight_kg=80, reps=6)],
        )
        match = _make_match(exercise_name="Unknown Thing", confidence=0.9)

        updated, update = self._apply(session, item, match)

        assert len(updated.exercises[1].sets) == 2
        assert update.exercise_index == 1

    def test_add_multiple_sets(self):
        existing = _make_session_exercise("Barbell Bench Press")
        session = _make_session(existing)
        item = _make_item(
            action="add_set",
            exercise_name="Barbell Bench Press",
            sets=[
                ParsedSet(weight_kg=80, reps=10),
                ParsedSet(weight_kg=80, reps=10),
                ParsedSet(weight_kg=80, reps=10),
            ],
        )
        match = _make_match(confidence=1.0)

        updated, _ = self._apply(session, item, match)

        assert len(updated.exercises[0].sets) == 3

    def test_update_last_set(self):
        existing = _make_session_exercise(
            "Barbell Bench Press",
            sets=[SetEntry(weight_kg=80, reps=10), SetEntry(weight_kg=80, reps=8)],
        )
        session = _make_session(existing)
        item = _make_item(
            action="update_last_set",
            exercise_name="Barbell Bench Press",
            sets=[ParsedSet(reps=12)],
        )
        match = _make_match(confidence=1.0)

        updated, update = self._apply(session, item, match)

        assert updated.exercises[0].sets[-1].reps == 12
        assert updated.exercises[0].sets[-1].weight_kg == 80
        assert update.action == "update_last_set"

    def test_update_last_set_preserves_unmentioned_fields(self):
        existing = _make_session_exercise(
            "Running",
            sets=[SetEntry(duration_seconds=1800, distance_m=5000)],
        )
        session = _make_session(existing)
        item = _make_item(
            action="update_last_set",
            exercise_name="Running",
            sets=[ParsedSet(distance_m=5500)],
        )
        match = _make_match(exercise_name="Running", confidence=1.0)

        updated, _ = self._apply(session, item, match)

        assert updated.exercises[0].sets[0].distance_m == 5500
        assert updated.exercises[0].sets[0].duration_seconds == 1800

    def test_remove_exercise(self):
        ex1 = _make_session_exercise("Bench Press")
        ex2 = _make_session_exercise("Squat")
        session = _make_session(ex1, ex2)
        item = _make_item(action="remove_exercise", exercise_name="Bench Press")
        match = _make_match(exercise_name="Bench Press", confidence=1.0)

        updated, update = self._apply(session, item, match)

        assert len(updated.exercises) == 1
        assert updated.exercises[0].exercise_name == "Squat"
        assert update.action == "remove_exercise"

    def test_remove_nonexistent_exercise_is_noop(self):
        ex = _make_session_exercise("Squat")
        session = _make_session(ex)
        item = _make_item(action="remove_exercise", exercise_name="Curls")
        match = _make_match(exercise_name="Curls", confidence=1.0)

        updated, update = self._apply(session, item, match)

        assert len(updated.exercises) == 1
        assert update.action == "remove_exercise"

    def test_finish_action(self):
        ex = _make_session_exercise("Bench Press")
        session = _make_session(ex)
        item = _make_item(action="finish", exercise_name=None)

        updated, update = self._apply(session, item)

        assert len(updated.exercises) == 1
        assert update.action == "finish"
        assert update.exercise_index is None

    def test_unclear_action(self):
        session = _make_session()
        item = _make_item(action="unclear", exercise_name=None)

        updated, update = self._apply(session, item)

        assert len(updated.exercises) == 0
        assert update.action == "unclear"

    def test_needs_confirmation_when_no_match(self):
        session = _make_session()
        item = _make_item(
            action="new_exercise",
            exercise_name="Skull Crushers",
            sets=[ParsedSet(weight_kg=30, reps=12)],
        )

        updated, update = self._apply(session, item, match=None)

        assert update.action == "needs_confirmation"
        assert update.spoken_exercise_name == "Skull Crushers"
        assert len(update.pending_sets) == 1
        assert update.pending_sets[0].weight_kg == 30

    def test_needs_confirmation_with_low_confidence(self):
        session = _make_session()
        item = _make_item(
            action="new_exercise",
            exercise_name="skulls",
            sets=[ParsedSet(weight_kg=30, reps=12)],
        )
        low_match = _make_match(
            exercise_name="Lying Triceps Press", confidence=0.6
        )
        alt = _make_match(exercise_name="Skull Crusher", confidence=0.5)

        updated, update = self._apply(session, item, low_match, candidates=[alt])

        assert update.action == "needs_confirmation"
        assert len(update.candidates) == 2
        assert update.candidates[0].exercise_name == "Lying Triceps Press"
        assert update.candidates[1].exercise_name == "Skull Crusher"

    def test_session_is_deep_copied(self):
        original_set = SetEntry(weight_kg=80, reps=10)
        ex = SessionExercise(exercise_name="Bench Press", sets=[original_set])
        session = _make_session(ex)
        item = _make_item(
            action="add_set",
            exercise_name="Bench Press",
            sets=[ParsedSet(weight_kg=80, reps=8)],
        )
        match = _make_match(exercise_name="Bench Press", confidence=1.0)

        updated, _ = self._apply(session, item, match)

        assert len(session.exercises[0].sets) == 1
        assert len(updated.exercises[0].sets) == 2


# ── Multi-exercise extraction ────────────────────────────────────────────────


class TestMultiExercise:
    def test_three_exercises_all_matched(self):
        svc = _make_service()
        session = _make_session()

        items = [
            _make_item("new_exercise", "Incline Dumbbell Press", [ParsedSet(weight_kg=45, reps=10)] * 3),
            _make_item("new_exercise", "Incline Bench Press", [ParsedSet(weight_kg=60, reps=10)] * 3),
            _make_item("new_exercise", "Cable Fly", [ParsedSet(reps=12)] * 3),
        ]

        matches = [
            _make_match("Incline_Dumbbell_Press", "Incline Dumbbell Press", 1.0),
            _make_match("Incline_Bench_Press", "Incline Bench Press", 1.0),
            _make_match("Cable_Fly", "Cable Fly", 1.0),
        ]

        current = session
        updates = []
        for item, match in zip(items, matches):
            current, update = svc._apply_item(
                session=current, item=item, match=match,
                candidates=[], interpretation="Got it",
            )
            updates.append(update)

        assert len(current.exercises) == 3
        assert current.exercises[0].exercise_name == "Incline Dumbbell Press"
        assert current.exercises[1].exercise_name == "Incline Bench Press"
        assert current.exercises[2].exercise_name == "Cable Fly"
        assert all(len(e.sets) == 3 for e in current.exercises)
        assert all(u.action == "new_exercise" for u in updates)

    def test_two_matched_one_needs_confirmation(self):
        svc = _make_service()
        session = _make_session()

        items = [
            _make_item("new_exercise", "Bench Press", [ParsedSet(weight_kg=80, reps=10)]),
            _make_item("new_exercise", "Some Weird Exercise", [ParsedSet(reps=12)]),
            _make_item("new_exercise", "Squat", [ParsedSet(weight_kg=100, reps=5)]),
        ]

        current = session
        updates = []

        current, u1 = svc._apply_item(
            session=current,
            item=items[0],
            match=_make_match("bench_press", "Bench Press", 1.0),
            candidates=[], interpretation="Got it",
        )
        updates.append(u1)

        current, u2 = svc._apply_item(
            session=current,
            item=items[1],
            match=None,
            candidates=[], interpretation="Got it",
        )
        updates.append(u2)

        current, u3 = svc._apply_item(
            session=current,
            item=items[2],
            match=_make_match("squat", "Squat", 1.0),
            candidates=[], interpretation="Got it",
        )
        updates.append(u3)

        assert len(current.exercises) == 2
        assert current.exercises[0].exercise_name == "Bench Press"
        assert current.exercises[1].exercise_name == "Squat"
        assert updates[0].action == "new_exercise"
        assert updates[1].action == "needs_confirmation"
        assert updates[1].spoken_exercise_name == "Some Weird Exercise"
        assert updates[2].action == "new_exercise"

    def test_extraction_items_schema(self):
        ext = VoiceWorkoutExtraction(
            items=[
                ExerciseActionItem(action="new_exercise", exercise_name="Bench Press", sets=[ParsedSet(reps=10)]),
                ExerciseActionItem(action="new_exercise", exercise_name="Squat", sets=[ParsedSet(reps=5)]),
            ],
            interpretation="Bench and Squat",
        )
        assert len(ext.items) == 2
        assert ext.items[0].exercise_name == "Bench Press"
        assert ext.items[1].exercise_name == "Squat"


# ── _match_exercise (DB integration) ────────────────────────────────────────


class TestMatchExercise:
    @pytest.mark.asyncio
    async def test_exact_name_match_confidence_1(self):
        svc = _make_service()
        row = _fake_exercise_row("bench_press", "Bench Press")
        session = FakeSession(results=[FakeResult(rows=[row])])

        best, candidates = await svc._match_exercise(
            "Bench Press", postgres_session=session
        )

        assert best is not None
        assert best.confidence == 1.0
        assert best.exercise_name == "Bench Press"
        assert candidates == []

    @pytest.mark.asyncio
    async def test_partial_match_confidence_085(self):
        svc = _make_service()
        row = _fake_exercise_row("barbell_bench_press", "Barbell Bench Press")
        session = FakeSession(results=[FakeResult(rows=[row])])

        best, candidates = await svc._match_exercise(
            "Bench Press", postgres_session=session
        )

        assert best is not None
        assert best.confidence == 0.85

    @pytest.mark.asyncio
    async def test_no_match_returns_none(self):
        svc = _make_service()
        session = FakeSession(results=[FakeResult(rows=[])])

        best, candidates = await svc._match_exercise(
            "Xyzzy Exercise", postgres_session=session
        )

        assert best is None
        assert candidates == []

    @pytest.mark.asyncio
    async def test_multiple_matches_sorted_by_confidence(self):
        svc = _make_service()
        exact = _fake_exercise_row("bench_press", "Bench Press")
        partial = _fake_exercise_row("incline_bench_press", "Incline Bench Press")
        session = FakeSession(results=[FakeResult(rows=[partial, exact])])

        best, candidates = await svc._match_exercise(
            "Bench Press", postgres_session=session
        )

        assert best.confidence == 1.0
        assert best.exercise_name == "Bench Press"
        assert len(candidates) == 1
        assert candidates[0].exercise_name == "Incline Bench Press"

    @pytest.mark.asyncio
    async def test_fuzzy_match_confidence_06(self):
        svc = _make_service()
        row = _fake_exercise_row("lat_pulldown", "Lat Pulldown")
        session = FakeSession(results=[FakeResult(rows=[row])])

        best, _ = await svc._match_exercise(
            "pulldowns", postgres_session=session
        )

        assert best is not None
        assert best.confidence == 0.6


# ── process_text_input (end-to-end through _interpret) ───────────────────────


class TestProcessTextInput:
    @pytest.mark.asyncio
    async def test_end_to_end_new_exercise(self):
        svc = _make_service()
        extraction = _make_extraction(
            action="new_exercise",
            exercise_name="Bench Press",
            sets=[ParsedSet(weight_kg=80, reps=10)],
            interpretation="Bench Press — 80kg × 10",
        )
        svc._gateway.extract = AsyncMock(return_value=(extraction, {}))

        row = _fake_exercise_row("bench_press", "Bench Press")
        fake_session = FakeSession(results=[FakeResult(rows=[row])])

        async def _fake_match(name, *, postgres_session=None):
            return await WorkoutVoiceService._match_exercise(
                svc, name, postgres_session=fake_session
            )

        svc._match_exercise = _fake_match

        session = _make_session()
        result = await svc.process_text_input(transcript="bench press 80kg 10 reps", session=session)

        assert result.transcript == "bench press 80kg 10 reps"
        assert result.update.action == "new_exercise"
        assert len(result.updates) == 1
        assert len(result.session.exercises) == 1
        assert result.session.exercises[0].exercise_name == "Bench Press"

    @pytest.mark.asyncio
    async def test_end_to_end_finish(self):
        svc = _make_service()
        extraction = _make_extraction(
            action="finish",
            exercise_name=None,
            interpretation="Workout complete!",
        )
        svc._gateway.extract = AsyncMock(return_value=(extraction, {}))

        ex = _make_session_exercise("Bench Press", [SetEntry(weight_kg=80, reps=10)])
        session = _make_session(ex)
        result = await svc.process_text_input(transcript="done", session=session)

        assert result.update.action == "finish"
        assert len(result.session.exercises) == 1

    @pytest.mark.asyncio
    async def test_end_to_end_multi_exercise(self):
        svc = _make_service()
        extraction = VoiceWorkoutExtraction(
            items=[
                ExerciseActionItem(
                    action="new_exercise",
                    exercise_name="Bench Press",
                    sets=[ParsedSet(weight_kg=80, reps=10)],
                ),
                ExerciseActionItem(
                    action="new_exercise",
                    exercise_name="Squat",
                    sets=[ParsedSet(weight_kg=100, reps=5)],
                ),
            ],
            interpretation="Bench Press and Squat logged",
        )
        svc._gateway.extract = AsyncMock(return_value=(extraction, {}))

        bench_row = _fake_exercise_row("bench_press", "Bench Press")
        squat_row = _fake_exercise_row("squat", "Squat")
        call_count = 0

        async def _fake_match(name, *, postgres_session=None):
            nonlocal call_count
            call_count += 1
            if "bench" in name.lower():
                row = bench_row
            else:
                row = squat_row
            fake_db = FakeSession(results=[FakeResult(rows=[row])])
            return await WorkoutVoiceService._match_exercise(
                svc, name, postgres_session=fake_db
            )

        svc._match_exercise = _fake_match

        session = _make_session()
        result = await svc.process_text_input(
            transcript="bench press 80kg 10 reps then squats 100kg 5 reps",
            session=session,
        )

        assert len(result.updates) == 2
        assert result.update.action == "new_exercise"
        assert len(result.session.exercises) == 2
        assert result.session.exercises[0].exercise_name == "Bench Press"
        assert result.session.exercises[1].exercise_name == "Squat"
        assert call_count == 2


# ── process_voice_input ─────────────────────────────────────────────────────


class TestProcessVoiceInput:
    @pytest.mark.asyncio
    async def test_empty_transcript_raises(self):
        svc = _make_service()
        svc._stt.transcribe = AsyncMock(
            return_value=SimpleNamespace(text="   ")
        )

        with pytest.raises(EmptyTranscriptError):
            await svc.process_voice_input(
                audio_bytes=b"fake",
                audio_format="m4a",
                session=_make_session(),
            )

    @pytest.mark.asyncio
    async def test_text_prepended_to_transcript(self):
        svc = _make_service()
        svc._stt.transcribe = AsyncMock(
            return_value=SimpleNamespace(text="80kg 10 reps")
        )

        extraction = _make_extraction(
            action="new_exercise",
            exercise_name="Bench Press",
            sets=[ParsedSet(weight_kg=80, reps=10)],
        )
        svc._gateway.extract = AsyncMock(return_value=(extraction, {}))

        row = _fake_exercise_row("bench_press", "Bench Press")
        fake_db = FakeSession(results=[FakeResult(rows=[row])])

        async def _fake_match(name, *, postgres_session=None):
            return await WorkoutVoiceService._match_exercise(
                svc, name, postgres_session=fake_db
            )

        svc._match_exercise = _fake_match

        result = await svc.process_voice_input(
            audio_bytes=b"fake",
            audio_format="m4a",
            session=_make_session(),
            text="bench press",
        )

        assert result.transcript == "bench press 80kg 10 reps"

    @pytest.mark.asyncio
    async def test_empty_audio_with_text_still_raises_if_both_empty(self):
        svc = _make_service()
        svc._stt.transcribe = AsyncMock(
            return_value=SimpleNamespace(text="")
        )

        with pytest.raises(EmptyTranscriptError):
            await svc.process_voice_input(
                audio_bytes=b"fake",
                audio_format="m4a",
                session=_make_session(),
                text="   ",
            )


# ── _build_user_message ─────────────────────────────────────────────────────


class TestBuildUserMessage:
    def test_empty_session_message(self):
        from lib.services.workout_voice_service import _build_user_message

        session = _make_session()
        msg = _build_user_message("bench press", session)
        assert 'Voice input: "bench press"' in msg
        assert "empty (this is the first exercise)" in msg

    def test_session_with_exercises(self):
        from lib.services.workout_voice_service import _build_user_message

        ex = _make_session_exercise(
            "Bench Press",
            [SetEntry(weight_kg=80, reps=10), SetEntry(weight_kg=80, reps=8)],
        )
        session = _make_session(ex)
        msg = _build_user_message("another set", session)
        assert "Bench Press" in msg
        assert "80" in msg and "kg" in msg
        assert "10 reps" in msg
        assert "Set 1:" in msg
        assert "Set 2:" in msg

    def test_set_with_duration_and_distance(self):
        from lib.services.workout_voice_service import _build_user_message

        ex = _make_session_exercise(
            "Running",
            [SetEntry(duration_seconds=1800, distance_m=5000)],
        )
        session = _make_session(ex)
        msg = _build_user_message("done", session)
        assert "1800s" in msg
        assert "5000" in msg and "m" in msg
