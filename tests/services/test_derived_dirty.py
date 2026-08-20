"""Dirty-cell store invariants: set semantics, and the claim/clear window that
lets a mid-drain re-mark survive (spec: docs/derived-data-spec.md §3-4)."""

from datetime import date, datetime, timezone

import pytest

from lib.derived.dirty import DirtyCellStore
from lib.derived.registry import DataDomain, defer_for


class _FakeDirtyCollection:
    def __init__(self):
        self.docs: dict[tuple, dict] = {}
        self._seq = 0

    async def bulk_write(self, ops, ordered=False):
        for op in ops:
            f = op._filter
            key = (f["patient_id"], f["domain"], f["date"])
            if key in self.docs:
                self.docs[key].update(op._doc["$set"])
            else:
                self._seq += 1
                self.docs[key] = {"_id": self._seq, **f, **op._doc["$set"]}

    def find(self, query):
        rows = [d for d in self.docs.values() if d["patient_id"] == query["patient_id"]]

        class _Cursor:
            async def to_list(self, length=None):
                return [dict(r) for r in rows]

        return _Cursor()

    async def delete_many(self, query):
        ids = set(query["_id"]["$in"])
        cutoff = query["marked_at"]["$lte"]
        self.docs = {
            k: d
            for k, d in self.docs.items()
            if not (d["_id"] in ids and d["marked_at"] <= cutoff)
        }

    async def count_documents(self, query, limit=None):
        return sum(1 for d in self.docs.values() if d["patient_id"] == query["patient_id"])

    async def create_index(self, *a, **k):
        return "dirty_cell_idx"


@pytest.mark.asyncio
async def test_mark_is_set_semantics():
    store = DirtyCellStore(_FakeDirtyCollection())
    d = date(2026, 8, 20)
    await store.mark("p1", "meal", [d])
    await store.mark("p1", "meal", [d])
    await store.mark("p1", "meal", [d])
    _, cells = await store.claim("p1")
    assert len(cells) == 1  # ten writes to one day = one cell


@pytest.mark.asyncio
async def test_clear_removes_claimed_cells():
    store = DirtyCellStore(_FakeDirtyCollection())
    await store.mark("p1", "cgm", [date(2026, 8, 19), date(2026, 8, 20)])
    claim_ts, cells = await store.claim("p1")
    assert len(cells) == 2
    await store.clear("p1", cells, claim_ts)
    assert not await store.has_dirty("p1")


@pytest.mark.asyncio
async def test_remark_during_drain_survives_clear():
    store = DirtyCellStore(_FakeDirtyCollection())
    d = date(2026, 8, 20)
    await store.mark("p1", "meal", [d])
    claim_ts, cells = await store.claim("p1")
    # A new mark lands while the drain is running: same cell, newer marked_at.
    await store.mark("p1", "meal", [d])
    await store.clear("p1", cells, claim_ts)
    assert await store.has_dirty("p1")  # the drain's self-re-enqueue picks it up


@pytest.mark.asyncio
async def test_claim_scoped_per_patient():
    store = DirtyCellStore(_FakeDirtyCollection())
    await store.mark("p1", "meal", [date(2026, 8, 20)])
    await store.mark("p2", "cgm", [date(2026, 8, 20)])
    _, cells = await store.claim("p1")
    assert {c["patient_id"] for c in cells} == {"p1"}


def test_defer_table():
    assert defer_for(DataDomain.CGM) == 900
    assert defer_for(DataDomain.MEAL) == 60
    assert defer_for(DataDomain.FITNESS) == 120
