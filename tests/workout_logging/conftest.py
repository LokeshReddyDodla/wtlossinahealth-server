"""Shared fixtures for patient workout tests.

We mock Postgres with a queue-driven FakeSession (same spirit as
tests/gamification/helpers.py but tailored to the workout service's access
patterns: scalar_one / scalar_one_or_none / scalars().all() / .all()).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time
from types import SimpleNamespace
from typing import Any, Callable, Iterable
from uuid import UUID, uuid4

import pytest


# ── FakeResult ────────────────────────────────────────────────────────────────


class FakeResult:
    """Minimal stand-in for sqlalchemy Result. Supports every access pattern
    used by PatientWorkoutService."""

    def __init__(
        self,
        *,
        rows: Iterable[Any] = (),
        scalar_value: Any = None,
        scalar_one_or_none: Any | None = None,
        scalar_one: Any | None = None,
    ):
        self._rows = list(rows)
        self._scalar_value = scalar_value
        self._scalar_one_or_none = scalar_one_or_none
        self._scalar_one = scalar_one

    def scalar_one(self):
        return self._scalar_one if self._scalar_one is not None else (
            self._rows[0] if self._rows else 0
        )

    def scalar_one_or_none(self):
        return (
            self._scalar_one_or_none
            if self._scalar_one_or_none is not None
            else (self._rows[0] if self._rows else None)
        )

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


# ── FakeSession ───────────────────────────────────────────────────────────────


@dataclass
class FakeSession:
    """Queue-driven async session.

    Tests push results in order; each `execute()` pops one. Missing results are
    explicit assertion failures so accidentally-firing queries fail loudly.
    """
    results: list[FakeResult | Callable] = field(default_factory=list)
    added: list[Any] = field(default_factory=list)
    deleted: list[Any] = field(default_factory=list)
    commit_count: int = 0
    refresh_calls: list[tuple[Any, tuple[str, ...]]] = field(default_factory=list)
    flush_count: int = 0
    # Objects returned via execute() — tracked so delete() can cascade into
    # their relationship collections the same way SQLAlchemy would.
    _known_parents: list[Any] = field(default_factory=list)

    async def execute(self, query):  # noqa: ANN001
        if not self.results:
            raise AssertionError(
                "FakeSession.execute() called but no result was queued"
            )
        result = self.results.pop(0)
        if callable(result):
            result = result(query)
        # Remember any rows returned so later delete() calls can cascade.
        if isinstance(result, FakeResult):
            for row in result._rows:
                if row not in self._known_parents:
                    self._known_parents.append(row)
            for attr in ("_scalar_one_or_none", "_scalar_one"):
                val = getattr(result, attr, None)
                if val is not None and val not in self._known_parents:
                    self._known_parents.append(val)
        return result

    def add(self, obj):
        self.added.append(obj)
        # Assign id if not set (mirrors real SQLAlchemy Column(default=uuid4)).
        # Also cascades into `exercises` relationship so nested rows get ids,
        # which is what SQLAlchemy does on flush.
        if getattr(obj, "id", None) is None:
            obj.id = uuid4()
        for child in getattr(obj, "exercises", []) or []:
            if getattr(child, "id", None) is None:
                child.id = uuid4()

    async def delete(self, obj):
        self.deleted.append(obj)
        # Emulate cascade-removal: when an exercise is deleted, it should
        # disappear from its parent workout's `exercises` collection the
        # same way SQLAlchemy does on flush.
        for parent in (*self.added, *self._known_parents):
            children = getattr(parent, "exercises", None)
            if isinstance(children, list) and obj in children:
                children.remove(obj)

    async def commit(self):
        self.commit_count += 1

    async def refresh(self, obj, fields=None):
        self.refresh_calls.append((obj, tuple(fields or ())))

    async def flush(self):
        self.flush_count += 1

    async def rollback(self):
        return None


# ── Common fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def patient_id() -> str:
    return str(uuid4())


@pytest.fixture
def another_patient_id() -> str:
    return str(uuid4())


@pytest.fixture
def workout_id() -> str:
    return str(uuid4())


@pytest.fixture
def today() -> date:
    return date(2026, 4, 20)


@pytest.fixture
def catalog_row_factory():
    """Factory for fake rows returned by `SELECT id, name FROM exercises WHERE id IN (...)`."""

    def _make(id_: str, name: str | None = None) -> SimpleNamespace:
        return SimpleNamespace(id=id_, name=name or id_.replace("_", " "))

    return _make


@pytest.fixture
def fake_postgres_store():
    """A stub PostgresStore with a no-op get_session. Tests inject their own
    FakeSession explicitly via postgres_session kwarg."""

    class _StubStore:
        engine = SimpleNamespace(pool=None)

    return _StubStore()
