"""A persistently failing brief generation must not re-run the LLM on every
poll — after one failed attempt it enters cooldown and get() returns a
terminal 'error' the frontend stops polling on."""

import asyncio
from types import SimpleNamespace

import pytest

from lib.services.patient_brief.service import PatientBriefService


class _FakeCollection:
    def __init__(self):
        self.doc = None

    async def find_one(self, *_a, **_k):
        return self.doc

    async def replace_one(self, _filter, doc, upsert=False):
        self.doc = {k: v for k, v in doc.items() if k != "_id"}

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
            assessment="watch", verdict="Stable — keep monitoring", narrative="All good."
        )


async def _drain(svc):
    tasks = list(svc._bg_tasks)
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_failed_generation_is_bounded_not_looping():
    agent = _RaisingAgent()
    svc = PatientBriefService(_FakeCollection(), agent)

    first = await svc.get("p1")
    await _drain(svc)  # background regen runs and fails
    second = await svc.get("p1")
    third = await svc.get("p1")
    await _drain(svc)

    assert first["status"] == "generating"
    assert second["status"] == "error"  # terminal — frontend stops polling
    assert third["status"] == "error"
    assert agent.calls == 1  # not re-run on every poll


@pytest.mark.asyncio
async def test_successful_generation_clears_failure_and_serves_ready():
    agent = _OkAgent()
    svc = PatientBriefService(_FakeCollection(), agent)

    generating = await svc.get("p2")
    await _drain(svc)
    ready = await svc.get("p2")

    assert generating["status"] == "generating"
    assert ready["status"] == "ready"
    assert ready["verdict"] == "Stable — keep monitoring"
    assert ready["refreshing"] is False
    assert agent.calls == 1
