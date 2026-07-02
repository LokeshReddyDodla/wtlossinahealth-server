"""Live ASGI tests for the health-query-agent API access-control paths.

Boots a FastAPI app with the real router and real auth dependency chain
(get_current_actor → resolve_patient_access / resolve_patient_ids_for_query),
mocking only identity (JWT), the DB session, and the DI container.

Locks the behaviors that protect patient data:
- Patients are always self-scoped: naming another patient's ID is either
  forced to self (memories) or rejected 403 (query)
- Care providers need an assignment link — 403 without it
- Rate limiter rejection → 429 with Retry-After
- query_v3 passes patient-scoped IDs to the agent
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.auth.base import get_current_user
from lib.dependencies.database import get_postgres_session
from lib.dependencies.service_dependencies import (
    get_care_provider_access_service,
    get_health_query_agent,
)

PATIENT_ID = uuid4()
OTHER_PATIENT_ID = uuid4()
CP_ID = uuid4()


# ── App factory ──────────────────────────────────────────────────────────────


def _mock_session_for(role: ProfileTypeEnum):
    """Session whose actor-model lookup returns a matching mock model."""
    if role == ProfileTypeEnum.PATIENT:
        model = SimpleNamespace(patient_id=PATIENT_ID)
    elif role == ProfileTypeEnum.CARE_PROVIDER:
        model = SimpleNamespace(care_provider_id=CP_ID, permissions={}, health_facility=None)
    else:
        model = SimpleNamespace(id=uuid4())

    result = MagicMock()
    result.scalars.return_value.first.return_value = model
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    return session


def _build_app(*, role: ProfileTypeEnum, actor_id, agent=None, access_service=None):
    from rest_server.v1.health_query_agent.router import router

    app = FastAPI()
    app.include_router(router)

    session = _mock_session_for(role)
    access_service = access_service or AsyncMock()

    app.dependency_overrides[get_current_user] = lambda: (actor_id, role.value)
    app.dependency_overrides[get_postgres_session] = lambda: session
    app.dependency_overrides[get_care_provider_access_service] = lambda: access_service
    if agent is not None:
        app.dependency_overrides[get_health_query_agent] = lambda: agent
    return app


@pytest_asyncio.fixture
async def _no_op_limiter():
    """Patch container.resolve so limiter allows and memory store is mocked."""
    from lib.ai_foundation.rate_limit.limiter import RateLimiter, RateLimitResult
    from lib.ai_foundation.memory.mongo_store import MongoMemoryStore

    limiter = MagicMock(spec=RateLimiter)
    limiter.check_and_record.return_value = RateLimitResult(
        allowed=True, remaining=100, limit=1000, reset_at=time.time() + 3600,
    )
    memory = AsyncMock()
    memory.get_patient_facts = AsyncMock(return_value=[])
    memory.upsert_patient_facts = AsyncMock()
    memory.delete_patient_fact = AsyncMock(return_value=True)

    def fake_resolve(cls):
        if cls is RateLimiter:
            return limiter
        if cls is MongoMemoryStore:
            return memory
        return MagicMock()

    with patch("lib.core.container.container.resolve", side_effect=fake_resolve):
        yield SimpleNamespace(limiter=limiter, memory=memory)


async def _client(app):
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": "Bearer test-token"},
    )


# ── Patient self-scoping ─────────────────────────────────────────────────────


class TestPatientSelfScoping:
    @pytest.mark.asyncio
    async def test_memory_write_forced_to_own_id(self, _no_op_limiter):
        """A patient adding a memory for ANOTHER patient writes to their own store."""
        app = _build_app(role=ProfileTypeEnum.PATIENT, actor_id=PATIENT_ID)
        async with await _client(app) as client:
            resp = await client.post(
                "/health-query-agent/memories",
                json={
                    "patient_id": str(OTHER_PATIENT_ID),  # someone else's ID
                    "key": "dietary_preference",
                    "value": "vegetarian",
                },
            )
        assert resp.status_code == 200
        call = _no_op_limiter.memory.upsert_patient_facts.call_args
        assert call.args[0] == str(PATIENT_ID)  # forced to self, not OTHER

    @pytest.mark.asyncio
    async def test_query_other_patient_rejected(self, _no_op_limiter):
        """A patient explicitly querying another patient's data gets 403."""
        agent = AsyncMock()
        app = _build_app(role=ProfileTypeEnum.PATIENT, actor_id=PATIENT_ID, agent=agent)
        async with await _client(app) as client:
            resp = await client.post(
                "/health-query-agent/query/v3",
                json={
                    "message": "How is my glucose?",
                    "patient_ids": [str(OTHER_PATIENT_ID)],
                },
            )
        assert resp.status_code == 403
        agent.run.assert_not_called()


# ── Care-provider assignment gating ─────────────────────────────────────────


class TestCareProviderAccess:
    @pytest.mark.asyncio
    async def test_unassigned_patient_memories_403(self, _no_op_limiter):
        access = AsyncMock()
        access.is_patient_assigned = AsyncMock(return_value=False)
        app = _build_app(
            role=ProfileTypeEnum.CARE_PROVIDER, actor_id=CP_ID, access_service=access,
        )
        async with await _client(app) as client:
            resp = await client.get(
                "/health-query-agent/memories",
                params={"patient_id": str(PATIENT_ID)},
            )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_assigned_patient_memories_200(self, _no_op_limiter):
        access = AsyncMock()
        access.is_patient_assigned = AsyncMock(return_value=True)
        app = _build_app(
            role=ProfileTypeEnum.CARE_PROVIDER, actor_id=CP_ID, access_service=access,
        )
        async with await _client(app) as client:
            resp = await client.get(
                "/health-query-agent/memories",
                params={"patient_id": str(PATIENT_ID)},
            )
        assert resp.status_code == 200
        access.is_patient_assigned.assert_awaited_once()


# ── Rate limiting ────────────────────────────────────────────────────────────


class TestRateLimit429:
    @pytest.mark.asyncio
    async def test_memory_write_returns_429(self, _no_op_limiter):
        from lib.ai_foundation.rate_limit.limiter import RateLimitResult

        _no_op_limiter.limiter.check_and_record.return_value = RateLimitResult(
            allowed=False, remaining=0, limit=1000, reset_at=time.time() + 60,
        )
        app = _build_app(role=ProfileTypeEnum.PATIENT, actor_id=PATIENT_ID)
        async with await _client(app) as client:
            resp = await client.post(
                "/health-query-agent/memories",
                json={
                    "patient_id": str(PATIENT_ID),
                    "key": "health_goal",
                    "value": "lose weight",
                },
            )
        assert resp.status_code == 429
        assert "Retry-After" in resp.headers
        _no_op_limiter.memory.upsert_patient_facts.assert_not_called()


# ── Agent scoping ────────────────────────────────────────────────────────────


class TestQueryV3Scoping:
    @pytest.mark.asyncio
    async def test_patient_query_scoped_to_own_id(self, _no_op_limiter):
        from lib.ai_foundation.agents.state import AgentOutput

        agent = AsyncMock()
        agent.run = AsyncMock(return_value=AgentOutput(message="ok", is_ready=True))
        agent.to_query_response = MagicMock(return_value={"final_response": "ok"})
        app = _build_app(role=ProfileTypeEnum.PATIENT, actor_id=PATIENT_ID, agent=agent)
        async with await _client(app) as client:
            resp = await client.post(
                "/health-query-agent/query/v3",
                json={"message": "How is my glucose?"},
            )
        assert resp.status_code == 200
        agent_input = agent.run.call_args.args[0]
        assert agent_input.context.patient_ids == [str(PATIENT_ID)]
        assert agent_input.context.user_role == "patient"
