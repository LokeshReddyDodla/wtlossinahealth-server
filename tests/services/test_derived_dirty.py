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


@pytest.mark.asyncio
async def test_meal_domain_computes_and_saves(monkeypatch):
    import lib.dependencies.service_dependencies as deps
    from lib.derived.domains.meal import MealReportDomain

    calls = {}

    class _Report:
        def model_dump(self):
            return {"date": "2026-08-20", "meal_count": 2}

    class _Processor:
        async def get_meal_report_by_date(self, patient_id, day):
            calls["computed"] = (patient_id, day)
            return _Report()

    class _Service:
        async def save_report(self, patient_id, report):
            calls["saved"] = report

    monkeypatch.setattr(deps, "get_meal_stats_processor", lambda: _Processor())
    monkeypatch.setattr(deps, "get_meal_report_service", lambda: _Service())

    await MealReportDomain().compute_daily("p1", date(2026, 8, 20))
    assert calls["computed"] == ("p1", date(2026, 8, 20))
    assert calls["saved"]["report_type"] == "daily"
    assert calls["saved"]["patient_id"] == "p1"


def test_registered_domains():
    from lib.derived.registry import get_report_domains

    domains = get_report_domains()
    for d in (DataDomain.MEAL, DataDomain.CGM, DataDomain.SLEEP, DataDomain.FITNESS):
        assert d in domains
    assert DataDomain.SMBG not in domains  # raw-read domains: panel reads them directly


def test_cgm_week_mondays():
    from lib.derived.domains.cgm import week_mondays

    # Wed Aug 19 + Thu Aug 20 2026 share a week; Mon Aug 24 starts the next.
    days = [date(2026, 8, 20), date(2026, 8, 19), date(2026, 8, 24)]
    assert week_mondays(days) == [date(2026, 8, 17), date(2026, 8, 24)]
    assert week_mondays([date(2026, 8, 17)]) == [date(2026, 8, 17)]


def test_contiguous_runs():
    from lib.derived.dirty import contiguous_runs

    days = [date(2026, 8, 20), date(2026, 8, 18), date(2026, 8, 19), date(2026, 8, 25)]
    assert contiguous_runs(days) == [
        (date(2026, 8, 18), date(2026, 8, 20)),
        (date(2026, 8, 25), date(2026, 8, 25)),
    ]
    assert contiguous_runs([]) == []


def test_month_and_week_windows():
    from lib.derived.domains.sleep import month_bounds, week_windows

    days = [date(2026, 12, 31), date(2027, 1, 1)]
    months = month_bounds(days)
    assert months[0][0].month == 12 and months[0][1].day == 31
    assert months[1][0] == __import__("datetime").datetime(2027, 1, 1)
    assert months[1][1].month == 1 and months[1][1].day == 31

    weeks = week_windows([date(2026, 8, 20)])  # Thursday
    assert weeks[0][0].date() == date(2026, 8, 17)  # Monday
    assert weeks[0][1].date() == date(2026, 8, 23)  # Sunday


def test_report_id_matches_legacy_scheme():
    # Ids are persisted — the shared helper MUST hash the exact legacy strings,
    # or every regenerated report duplicates instead of replacing.
    import hashlib

    from lib.services.reports.base import report_id

    assert report_id("p1", "daily", "2026-08-20T00:00:00", "2026-08-20T23:59:59") == (
        hashlib.sha256(b"p1_daily_2026-08-20T00:00:00_2026-08-20T23:59:59").hexdigest()
    )
    # CGM custom / meal daily omit the end
    assert report_id("p1", "custom", "2026-08-20T00:00:00") == (
        hashlib.sha256(b"p1_custom_2026-08-20T00:00:00").hexdigest()
    )


def test_slice_readings_around_meal_matches_per_meal_query_semantics():
    from datetime import datetime, timedelta

    from lib.services.reports.meal.daily_stats import slice_readings_around_meal

    meal_time = datetime(2026, 8, 20, 13, 0)
    readings = [
        (meal_time + timedelta(minutes=m), 100.0 + m)
        for m in (-45, -30, -10, 0, 15, 60, 90, 91)
    ]
    before, after = slice_readings_around_meal(readings, meal_time)
    # -45 is outside the 30-min lead-in; +91 outside the 90-min tail;
    # the reading AT meal_time counts as "after" (matches r[0] >= meal_time).
    assert [r[0] for r in before] == [meal_time - timedelta(minutes=30), meal_time - timedelta(minutes=10)]
    assert [r[0] for r in after] == [meal_time + timedelta(minutes=m) for m in (0, 15, 60, 90)]
