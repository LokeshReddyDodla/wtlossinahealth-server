"""Unit tests for WorkoutTextReprBuilder (Qdrant embedding text)."""
from __future__ import annotations

from lib.services.vector.workout.text_builder import WorkoutTextReprBuilder


class TestWorkoutTextReprBuilder:
    def test_full_workout_produces_all_sections(self):
        text = WorkoutTextReprBuilder.build({
            "type": "strength",
            "date": "2026-04-20",
            "time": "18:30",
            "duration_minutes": 55,
            "intensity": "vigorous",
            "calories_burned": 420.0,
            "notes": "Felt strong",
            "exercises": [
                {
                    "exercise_id": "Bench_Press",
                    "exercise_name": "Barbell Bench Press",
                    "sets": 3, "reps": 10, "weight_kg": 60.0,
                },
                {
                    "exercise_id": "Squat",
                    "exercise_name": "Back Squat",
                    "sets": 5, "reps": 5, "weight_kg": 100.0,
                },
            ],
        })
        assert "Strength workout on 2026-04-20" in text
        assert "18:30" in text
        assert "55 min" in text
        assert "vigorous" in text
        assert "Barbell Bench Press: 3x10 @ 60.0kg" in text
        assert "Back Squat: 5x5 @ 100.0kg" in text
        assert "Calories burned: 420.0" in text
        assert "Felt strong" in text

    def test_minimal_workout_no_exercises(self):
        text = WorkoutTextReprBuilder.build({
            "type": "cardio",
            "date": "2026-04-20",
            "exercises": [],
        })
        assert "Cardio workout on 2026-04-20" in text
        assert "Exercises:" not in text

    def test_cardio_exercise_with_duration_and_distance(self):
        text = WorkoutTextReprBuilder.build({
            "type": "cardio",
            "date": "2026-04-20",
            "exercises": [
                {
                    "exercise_name": "Running",
                    "duration_seconds": 1800,
                    "distance_m": 5000.0,
                },
            ],
        })
        assert "Running:" in text
        assert "1800s" in text
        assert "5000.0m" in text

    def test_exercise_without_details_renders_name_only(self):
        text = WorkoutTextReprBuilder.build({
            "type": "mobility",
            "date": "2026-04-20",
            "exercises": [{"exercise_name": "Foam Rolling"}],
        })
        # No "- Foam Rolling:" (no colon when no details)
        assert "Foam Rolling" in text
        assert "Foam Rolling:" not in text

    def test_falls_back_to_exercise_id_when_name_missing(self):
        text = WorkoutTextReprBuilder.build({
            "type": "strength",
            "date": "2026-04-20",
            "exercises": [{"exercise_id": "Bench_Press"}],
        })
        assert "Bench_Press" in text

    def test_handles_empty_notes_gracefully(self):
        text = WorkoutTextReprBuilder.build({
            "type": "strength",
            "date": "2026-04-20",
            "notes": "   ",
            "exercises": [],
        })
        assert "Notes:" not in text

    def test_missing_type_defaults_to_workout(self):
        text = WorkoutTextReprBuilder.build({
            "date": "2026-04-20",
            "exercises": [],
        })
        assert "Workout workout" in text or "workout on 2026-04-20" in text.lower()

    def test_sets_without_reps_renders_sets_only(self):
        text = WorkoutTextReprBuilder.build({
            "type": "mobility",
            "date": "2026-04-20",
            "exercises": [
                {"exercise_name": "Plank", "sets": 3, "duration_seconds": 60},
            ],
        })
        assert "3 sets" in text
        assert "60s" in text
