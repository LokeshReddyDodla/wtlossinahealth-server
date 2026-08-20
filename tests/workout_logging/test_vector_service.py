"""Unit tests for WorkoutVectorService."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from lib.services.vector.workout.service import WorkoutVectorService


def _store_with_client(client):
    store = SimpleNamespace()

    class _Ctx:
        async def __aenter__(self):
            return client

        async def __aexit__(self, exc_type, exc, tb):
            return False

    store.get_client = lambda: _Ctx()

    async def _upsert_points(collection_name, points):
        await client.upsert(collection_name=collection_name, points=points)

    store.upsert_points = _upsert_points
    return store


class TestBuildPoint:
    @pytest.mark.asyncio
    async def test_rich_workout_produces_expected_payload(self):
        client = MagicMock()
        client.upsert = AsyncMock()
        service = WorkoutVectorService(qdrant_store=_store_with_client(client))

        workout = {
            "date": "2026-04-20",
            "time": "18:30:00",
            "type": "strength",
            "duration_minutes": 55,
            "intensity": "vigorous",
            "calories_burned": 420.0,
            "fitness_plan_session_id": None,
            "source": "app",
            "exercises": [
                {
                    "exercise_id": "Bench_Press",
                    "exercise_name": "Bench Press",
                    "sets": 3, "reps": 10, "weight_kg": 60.0,
                },
                {
                    "exercise_id": "Squat",
                    "exercise_name": "Back Squat",
                    "sets": 5, "reps": 5, "weight_kg": 100.0,
                },
            ],
        }

        point = await service._build_point(
            patient_id="p1",
            workout_id="w1",
            workout=workout,
            patient_age=30,
            patient_gender="male",
        )

        # Text repr is populated and mentions key details
        assert "Bench Press" in point["text"]
        assert "Back Squat" in point["text"]
        # Payload carries denormalized fields for filtering
        payload = point["payload"]
        assert payload["data_type"] == "patient_workout"
        assert payload["exercise_count"] == 2
        assert payload["exercise_ids"] == ["Bench_Press", "Squat"]
        assert payload["exercise_names"] == ["Bench Press", "Back Squat"]
        # volume = (3*10*60) + (5*5*100) = 1800 + 2500 = 4300
        assert payload["total_volume_kg"] == 4300.0
        assert payload["duration_minutes"] == 55
        assert payload["intensity"] == "vigorous"

    @pytest.mark.asyncio
    async def test_empty_exercises_sets_volume_to_none(self):
        service = WorkoutVectorService(qdrant_store=_store_with_client(MagicMock()))
        point = await service._build_point(
            patient_id="p1",
            workout_id="w1",
            workout={
                "date": "2026-04-20",
                "type": "cardio",
                "duration_minutes": 30,
                "exercises": [],
            },
            patient_age=30,
            patient_gender="male",
        )
        assert point["payload"]["exercise_count"] == 0
        assert point["payload"]["total_volume_kg"] is None

    @pytest.mark.asyncio
    async def test_missing_time_defaults_to_midnight(self):
        service = WorkoutVectorService(qdrant_store=_store_with_client(MagicMock()))
        point = await service._build_point(
            patient_id="p1", workout_id="w1",
            workout={"date": "2026-04-20", "type": "cardio", "exercises": []},
            patient_age=30, patient_gender="male",
        )
        # Should not raise and should produce a valid payload
        assert point["payload"]["date"] == "2026-04-20"

    @pytest.mark.asyncio
    async def test_deterministic_point_id_from_workout_id(self):
        service = WorkoutVectorService(qdrant_store=_store_with_client(MagicMock()))
        w = {"date": "2026-04-20", "type": "strength", "exercises": []}

        a = await service._build_point("p1", "same-id", w, 30, "male")
        b = await service._build_point("p2", "same-id", w, 40, "female")

        # Same workout_id → same point id regardless of patient/age
        assert a["id"] == b["id"]

    @pytest.mark.asyncio
    async def test_different_workout_ids_produce_different_points(self):
        service = WorkoutVectorService(qdrant_store=_store_with_client(MagicMock()))
        w = {"date": "2026-04-20", "type": "strength", "exercises": []}

        a = await service._build_point("p1", "w1", w, 30, "male")
        b = await service._build_point("p1", "w2", w, 30, "male")
        assert a["id"] != b["id"]


class TestUpsertWorkout:
    @pytest.mark.asyncio
    async def test_upsert_calls_qdrant_with_embedded_point(self, monkeypatch):
        client = MagicMock()
        client.upsert = AsyncMock()
        service = WorkoutVectorService(qdrant_store=_store_with_client(client))

        async def _fake_embed(_text):
            return [0.1, 0.2, 0.3]

        monkeypatch.setattr(
            "lib.services.vector.workout.service.embed_text", _fake_embed
        )

        result = await service.upsert_workout(
            patient_id="p1",
            workout_id="w1",
            workout={
                "date": "2026-04-20",
                "type": "strength",
                "exercises": [],
            },
            patient_age=30,
            patient_gender="male",
        )

        assert result == {"points_created": 1}
        client.upsert.assert_called_once()
        call = client.upsert.call_args
        assert call.kwargs["collection_name"] == "patient_data"
        points = call.kwargs["points"]
        assert len(points) == 1
        assert points[0].vector == [0.1, 0.2, 0.3]

    @pytest.mark.asyncio
    async def test_embedding_failure_raises_vector_service_error(
        self, monkeypatch
    ):
        from lib.services.vector.utils.exceptions import VectorServiceError

        service = WorkoutVectorService(qdrant_store=_store_with_client(MagicMock()))

        async def _broken_embed(_text):
            raise RuntimeError("model offline")

        monkeypatch.setattr(
            "lib.services.vector.workout.service.embed_text", _broken_embed
        )

        with pytest.raises(VectorServiceError):
            await service.upsert_workout(
                patient_id="p1",
                workout_id="w1",
                workout={"date": "2026-04-20", "type": "cardio", "exercises": []},
                patient_age=30,
                patient_gender="male",
            )

    @pytest.mark.asyncio
    async def test_empty_embedding_skips_upsert(self, monkeypatch):
        client = MagicMock()
        client.upsert = AsyncMock()
        service = WorkoutVectorService(qdrant_store=_store_with_client(client))

        async def _empty(_text):
            return None

        monkeypatch.setattr(
            "lib.services.vector.workout.service.embed_text", _empty
        )
        result = await service.upsert_workout(
            patient_id="p1",
            workout_id="w1",
            workout={"date": "2026-04-20", "type": "cardio", "exercises": []},
            patient_age=30,
            patient_gender="male",
        )
        assert result == {"points_created": 1}
        client.upsert.assert_not_called()


class TestDeletes:
    @pytest.mark.asyncio
    async def test_delete_workout_vector_uses_deterministic_id(self, monkeypatch):
        service = WorkoutVectorService(qdrant_store=_store_with_client(MagicMock()))
        deleted = []

        async def _fake_delete(ids):
            deleted.append(ids)

        monkeypatch.setattr(service, "delete_points_by_ids", _fake_delete)
        await service.delete_workout_vector("w1")
        assert len(deleted) == 1
        assert len(deleted[0]) == 1

    @pytest.mark.asyncio
    async def test_delete_workout_vectors_for_patient_filters_by_data_type(
        self, monkeypatch
    ):
        service = WorkoutVectorService(qdrant_store=_store_with_client(MagicMock()))
        calls = []

        async def _fake_delete_filter(patient_id, data_type=None):
            calls.append((patient_id, data_type))

        monkeypatch.setattr(service, "delete_points_by_filter", _fake_delete_filter)
        await service.delete_workout_vectors_for_patient("p1")
        assert calls == [("p1", "patient_workout")]
