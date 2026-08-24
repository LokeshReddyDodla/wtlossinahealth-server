"""A persistently failing brief generation must not re-run the LLM on every
poll — after the worker exhausts retries it enters cooldown and get() returns a
terminal 'error' the frontend stops polling on."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from lib.services.patient_brief.service import PatientBriefService
from lib.workers.tasks.patient_brief.tasks import generate_patient_brief


class _FakeCollection:
    def __init__(self):
        self.doc = None

    async def find_one(self, *_a, **_k):
        return dict(self.doc) if self.doc else None

    async def replace_one(self, _filter, doc, upsert=False):
        self.doc = {k: v for k, v in doc.items() if k != "_id"}

    async def update_one(self, flt, update, upsert=False):
        base = self.doc or {"patient_id": flt.get("patient_id")}
        base.update(update.get("$set", {}))
        for key in update.get("$unset", {}):
            base.pop(key, None)
        self.doc = base

    async def create_index(self, *_a, **_k):
        return None


class _RaisingAgent:
    def __init__(self):
        self.calls = 0

    async def run_provider_brief(self, *, patient_id):
        self.calls += 1
        raise RuntimeError("LLM down")


class _OkAgent:
    def __init__(self):
        self.calls = 0

    async def run_provider_brief(self, *, patient_id):
        self.calls += 1
        return SimpleNamespace(
            assessment="watch",
            verdict="Stable — keep monitoring",
            narrative="All good.",
        )


def _stub_enqueue(monkeypatch):
    calls = []

    async def enqueue(patient_id, *, requested_at):
        calls.append((patient_id, requested_at))
        return f"job:{patient_id}"

    monkeypatch.setattr(
        "lib.workers.tasks.patient_brief.tasks.enqueue_patient_brief", enqueue
    )
    return calls


@pytest.mark.asyncio
async def test_failed_generation_is_bounded_not_looping(monkeypatch):
    calls = _stub_enqueue(monkeypatch)
    agent = _RaisingAgent()
    svc = PatientBriefService(_FakeCollection(), agent)

    first = await svc.get("p1")
    with pytest.raises(RuntimeError):
        await svc.regenerate("p1")
    await svc.mark_failed("p1")
    second = await svc.get("p1")
    third = await svc.get("p1")

    assert first["status"] == "generating"
    assert second["status"] == "error"  # terminal — frontend stops polling
    assert third["status"] == "error"
    assert agent.calls == 1
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_failure_cooldown_is_shared_across_workers(monkeypatch):
    _stub_enqueue(monkeypatch)
    col = _FakeCollection()
    agent = _RaisingAgent()
    worker_a = PatientBriefService(col, agent)
    worker_b = PatientBriefService(col, _RaisingAgent())

    await worker_a.get("p3")
    with pytest.raises(RuntimeError):
        await worker_a.regenerate("p3")
    await worker_a.mark_failed("p3")

    # Worker B, with no in-memory record, still sees the persisted cooldown.
    assert (await worker_b.get("p3"))["status"] == "error"


@pytest.mark.asyncio
async def test_successful_generation_clears_failure_and_serves_ready(
    monkeypatch,
):
    _stub_enqueue(monkeypatch)
    agent = _OkAgent()
    svc = PatientBriefService(_FakeCollection(), agent)

    generating = await svc.get("p2")
    await svc.regenerate("p2")
    ready = await svc.get("p2")

    assert generating["status"] == "generating"
    assert ready["status"] == "ready"
    assert ready["verdict"] == "Stable — keep monitoring"
    assert ready["refreshing"] is False
    assert agent.calls == 1


@pytest.mark.asyncio
async def test_worker_marks_failure_only_after_final_retry():
    service = SimpleNamespace(
        regenerate=AsyncMock(side_effect=RuntimeError("LLM down")),
        mark_failed=AsyncMock(),
    )
    container = SimpleNamespace(resolve=lambda _service_type: service)

    with pytest.raises(RuntimeError):
        await generate_patient_brief.__wrapped__(
            {"container": container, "job_try": 1}, "p4"
        )
    service.mark_failed.assert_not_awaited()

    with pytest.raises(RuntimeError):
        await generate_patient_brief.__wrapped__(
            {"container": container, "job_try": 2}, "p4"
        )
    service.mark_failed.assert_awaited_once_with("p4")


@pytest.mark.asyncio
async def test_worker_clears_lease_when_service_construction_fails():
    collection = _FakeCollection()
    await collection.update_one(
        {"patient_id": "p7"},
        {
            "$set": {
                "generation_started_at": object(),
            }
        },
        upsert=True,
    )

    def resolve(dependency):
        if dependency == "patient_briefs_collection":
            return collection
        raise RuntimeError("dependency construction failed")

    with pytest.raises(RuntimeError, match="dependency construction"):
        await generate_patient_brief.__wrapped__(
            {"container": SimpleNamespace(resolve=resolve), "job_try": 2},
            "p7",
        )

    assert "generation_started_at" not in collection.doc
    assert "failed_at" in collection.doc


@pytest.mark.asyncio
async def test_expired_lease_ends_polling_instead_of_requeueing():
    collection = _FakeCollection()
    await collection.update_one(
        {"patient_id": "p8"},
        {
            "$set": {
                "generation_started_at": datetime.now(timezone.utc)
                - timedelta(minutes=11)
            }
        },
        upsert=True,
    )
    svc = PatientBriefService(collection, _OkAgent())

    result = await svc.get("p8")

    assert result == {"status": "error"}
    assert "generation_started_at" not in collection.doc
