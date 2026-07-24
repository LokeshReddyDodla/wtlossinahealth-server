"""expire_ended_plans mechanics — flip ended ACTIVE plans to EXPIRED and
re-vectorize. The selection predicate (ACTIVE + end_date < today, non-null) is
a SQL where-clause exercised against a real DB by the backfill; here a fake
session returns the qualifying rows so we lock the state change + sync.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from lib.services.patient_diet_plan_service import PatientDietPlanService


class _Scalars:
    def __init__(self, items):
        self._items = items

    def all(self):
        return self._items


class _Result:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return _Scalars(self._items)


class _FakeSession:
    def __init__(self, rows):
        self._rows = rows
        self.commits = 0

    async def execute(self, _stmt):
        return _Result(self._rows)

    async def commit(self):
        self.commits += 1

    async def refresh(self, _obj):
        pass


def _service():
    svc = PatientDietPlanService(
        postgres_store=MagicMock(),
        plans_vector_service=MagicMock(),
        patient_profile_service=MagicMock(),
    )
    svc._vectorize_diet_plan = AsyncMock()
    return svc


@pytest.mark.asyncio
async def test_expires_and_revectorizes_ended_plans():
    svc = _service()
    plans = [SimpleNamespace(status="ACTIVE"), SimpleNamespace(status="ACTIVE")]
    session = _FakeSession(plans)

    n = await svc.expire_ended_plans(postgres_session=session)

    assert n == 2
    assert all(p.status == "EXPIRED" for p in plans)
    assert session.commits == 1
    assert svc._vectorize_diet_plan.await_count == 2


@pytest.mark.asyncio
async def test_no_ended_plans_is_a_noop():
    svc = _service()
    session = _FakeSession([])

    n = await svc.expire_ended_plans(postgres_session=session)

    assert n == 0
    assert session.commits == 0
    svc._vectorize_diet_plan.assert_not_awaited()
