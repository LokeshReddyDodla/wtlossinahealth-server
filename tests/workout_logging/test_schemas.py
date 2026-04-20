"""Unit tests for Pydantic schemas in lib/schemas/patient_workout.py."""
from __future__ import annotations

from datetime import date, time
from uuid import uuid4

import pytest
from pydantic import ValidationError

from lib.schemas.patient_workout import (
    PatientWorkoutCreate,
    PatientWorkoutExerciseInput,
    PatientWorkoutUpdate,
)


class TestPatientWorkoutExerciseInput:
    def test_accepts_minimal_fields(self):
        ex = PatientWorkoutExerciseInput(exercise_id="Bench_Press")
        assert ex.exercise_id == "Bench_Press"
        assert ex.order_index == 0
        assert ex.sets is None and ex.reps is None

    def test_rejects_negative_sets(self):
        with pytest.raises(ValidationError):
            PatientWorkoutExerciseInput(exercise_id="x", sets=0)

    def test_rejects_negative_weight(self):
        with pytest.raises(ValidationError):
            PatientWorkoutExerciseInput(exercise_id="x", weight_kg=-1.0)

    def test_accepts_full_strength_shape(self):
        ex = PatientWorkoutExerciseInput(
            exercise_id="Bench_Press",
            order_index=2,
            sets=3,
            reps=10,
            weight_kg=60.0,
            notes="heavy",
        )
        assert ex.sets == 3 and ex.reps == 10 and ex.weight_kg == 60.0

    def test_accepts_cardio_shape(self):
        ex = PatientWorkoutExerciseInput(
            exercise_id="Running",
            duration_seconds=1800,
            distance_m=5000.0,
        )
        assert ex.duration_seconds == 1800 and ex.distance_m == 5000.0


class TestPatientWorkoutCreate:
    def test_minimal_payload(self):
        w = PatientWorkoutCreate(date=date(2026, 4, 20), type="strength")
        assert w.exercises == []
        assert w.source == "app"
        assert w.fitness_plan_session_id is None

    def test_rejects_invalid_type(self):
        with pytest.raises(ValidationError):
            PatientWorkoutCreate(date=date(2026, 4, 20), type="yoga")

    def test_rejects_invalid_intensity(self):
        with pytest.raises(ValidationError):
            PatientWorkoutCreate(
                date=date(2026, 4, 20), type="strength", intensity="maximum"
            )

    def test_accepts_all_type_values(self):
        for t in ("strength", "cardio", "hiit", "mobility", "mixed", "other"):
            PatientWorkoutCreate(date=date(2026, 4, 20), type=t)

    def test_accepts_all_intensity_values(self):
        for i in ("light", "moderate", "vigorous"):
            PatientWorkoutCreate(
                date=date(2026, 4, 20), type="strength", intensity=i
            )

    def test_rejects_negative_duration(self):
        with pytest.raises(ValidationError):
            PatientWorkoutCreate(
                date=date(2026, 4, 20), type="strength", duration_minutes=-5
            )

    def test_accepts_optional_plan_session_id(self):
        sess = uuid4()
        w = PatientWorkoutCreate(
            date=date(2026, 4, 20),
            type="strength",
            fitness_plan_session_id=sess,
        )
        assert w.fitness_plan_session_id == sess

    def test_accepts_nested_exercises(self):
        w = PatientWorkoutCreate(
            date=date(2026, 4, 20),
            time=time(18, 30),
            type="strength",
            exercises=[
                {"exercise_id": "Bench_Press", "order_index": 0, "sets": 3, "reps": 10},
                {"exercise_id": "Squat", "order_index": 1, "sets": 3, "reps": 8},
            ],
        )
        assert len(w.exercises) == 2
        assert w.exercises[0].exercise_id == "Bench_Press"


class TestPatientWorkoutUpdate:
    def test_all_fields_optional(self):
        u = PatientWorkoutUpdate()
        assert u.date is None and u.type is None and u.exercises is None

    def test_exercises_none_means_no_replacement(self):
        u = PatientWorkoutUpdate(notes="updated")
        assert u.exercises is None
        assert u.notes == "updated"

    def test_empty_exercises_list_means_clear(self):
        u = PatientWorkoutUpdate(exercises=[])
        assert u.exercises == []
