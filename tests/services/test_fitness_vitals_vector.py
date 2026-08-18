"""Fitness-upload vitals → vector snapshot."""

import datetime as dt

import pytest

from lib.services.fitness_upload_service import FitnessUploadService


@pytest.mark.asyncio
async def test_fitness_vitals_snapshot(monkeypatch):
    captured: dict = {}

    async def fake_enqueue(patient_id, vital_id, vital_data):
        captured.update(pid=patient_id, vid=vital_id, data=vital_data)

    monkeypatch.setattr(
        "lib.services.fitness_upload_service.enqueue_generate_vital_vector_async",
        fake_enqueue,
    )

    svc = FitnessUploadService(None, None, None)
    t1 = dt.datetime(2026, 8, 10, 8, 0)
    t2 = dt.datetime(2026, 8, 10, 20, 0)
    points = [
        {"type": "heart_rate", "value": 70, "time": t1, "source_name": "apple"},
        {"type": "heart_rate", "value": 82, "time": t2, "source_name": "apple"},
        {"type": "blood_oxygen", "value": 97, "time": t1, "source_name": "apple"},
        {"type": "resting_heart_rate", "value": 55, "time": t2, "source_name": "apple"},
        {"type": "weight", "value": 80.5, "time": t2, "source_name": "apple"},
    ]
    await svc._enqueue_vitals_vector("p1", points)

    d = captured["data"]
    assert d["heart_rate"] == 82
    assert d["resting_heart_rate"] == 55
    assert d["spo2"] == 97
    assert d["weight"] == 80.5
    assert d["test_time"] == t2
    assert captured["vid"] == "fitness:p1:2026-08-10"


@pytest.mark.asyncio
async def test_no_vectorized_vitals_enqueues_nothing(monkeypatch):
    called = False

    async def fake_enqueue(*a, **k):
        nonlocal called
        called = True

    monkeypatch.setattr(
        "lib.services.fitness_upload_service.enqueue_generate_vital_vector_async",
        fake_enqueue,
    )
    svc = FitnessUploadService(None, None, None)
    await svc._enqueue_vitals_vector("p1", [{"type": "active_energy", "value": 300, "time": dt.datetime(2026, 8, 10)}])
    assert called is False
