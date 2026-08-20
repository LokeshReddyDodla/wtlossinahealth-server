"""Dirty-cell store + mark API (spec: docs/derived-data-spec.md §3-4).

`mark_dirty()` is the single line every producer adds: upsert the changed
(patient, domain, date) cells and kick the per-patient drain. Set semantics
give coalescing for free — ten writes to the same day are one cell — and
cells clear only after a successful drain, so a lost enqueue or dead worker
leaves durable evidence instead of a silent gap.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable

from loguru import logger
from pymongo import UpdateOne

COLLECTION_NAME = "derived_dirty_cells"
REFRESH_TASK = "refresh_patient"
_RE_ENQUEUE_DEFER_S = 30
# Backfills can legitimately touch months; anything wider is almost certainly
# a caller bug and would bloat the cell set.
_MAX_DATES_PER_MARK = 366


def _refresh_job_id(patient_id: str, deferred: bool = False) -> str:
    # Stable per-patient id: arq drops a duplicate while one is queued or
    # running (keep_result=0 keeps the result key from blocking re-enqueue).
    # Marks landing mid-run are covered by the drain's self-re-enqueue.
    # Deferred (background-stream) kicks ride their own id so a pending slow
    # job can never absorb-and-delay a user-action's immediate kick; the
    # occasional extra run finds an empty dirty set and costs one cheap
    # finalizer pass.
    return f"derived:refresh:{patient_id}:deferred" if deferred else f"derived:refresh:{patient_id}"


class DirtyCellStore:
    def __init__(self, collection: Any):
        self._col = collection

    async def ensure_indexes(self) -> None:
        await self._col.create_index(
            [("patient_id", 1), ("domain", 1), ("date", 1)],
            name="dirty_cell_idx",
            unique=True,
        )

    async def mark(self, patient_id: str, domain: str, dates: Iterable[date]) -> int:
        now = datetime.now(timezone.utc)
        ops = [
            UpdateOne(
                {"patient_id": patient_id, "domain": domain, "date": d.isoformat()},
                {"$set": {"marked_at": now}},
                upsert=True,
            )
            for d in list(dates)[:_MAX_DATES_PER_MARK]
        ]
        if not ops:
            return 0
        await self._col.bulk_write(ops, ordered=False)
        return len(ops)

    async def claim(self, patient_id: str) -> tuple[datetime, list[dict]]:
        claim_ts = datetime.now(timezone.utc)
        cells = await self._col.find({"patient_id": patient_id}).to_list(length=None)
        return claim_ts, cells

    async def clear(self, patient_id: str, cells: list[dict], claim_ts: datetime) -> None:
        # Only cells unchanged since the claim: a cell re-marked mid-drain has
        # a newer marked_at, survives, and the self-re-enqueue picks it up.
        if not cells:
            return
        await self._col.delete_many(
            {
                "_id": {"$in": [c["_id"] for c in cells]},
                "marked_at": {"$lte": claim_ts},
            }
        )

    async def has_dirty(self, patient_id: str) -> bool:
        return await self._col.count_documents({"patient_id": patient_id}, limit=1) > 0


def get_dirty_store() -> DirtyCellStore:
    from lib.core.container import container
    from lib.core.mongo_store import MongoStore

    store = container.resolve(MongoStore)
    return DirtyCellStore(store.get_collection(COLLECTION_NAME))


async def enqueue_refresh_patient(patient_id: str, defer_s: int | None = None) -> None:
    """Fire-and-forget drain kick for one patient. Never raises."""
    from lib.workers.arq.config import Queues
    from lib.workers.arq.redis import enqueue_job

    try:
        await enqueue_job(
            REFRESH_TASK,
            patient_id,
            _job_id=_refresh_job_id(patient_id, deferred=bool(defer_s)),
            _queue_name=Queues.REPORTS,
            _defer_by=timedelta(seconds=defer_s) if defer_s else None,
        )
    except Exception as e:
        logger.warning(f"Failed to enqueue derived refresh for {patient_id}: {e}")


async def mark_dirty(
    patient_id: str,
    domain: "DataDomain | str",
    dates: Iterable[date] | None = None,
    defer_s: int | None = None,
) -> None:
    """Record that a patient's data changed and kick the drain. Never raises —
    this sits in write paths and must not fail a save; a lost mark is healed
    by the next activity or a provider panel view."""
    from lib.derived.registry import DataDomain, defer_for

    domain = DataDomain(domain)
    try:
        cell_dates = list(dates) if dates else [datetime.now(timezone.utc).date()]
        await get_dirty_store().mark(str(patient_id), domain.value, cell_dates)
    except Exception as e:
        logger.warning(f"mark_dirty failed for {patient_id}/{domain.value}: {e}")
    await enqueue_refresh_patient(str(patient_id), defer_s if defer_s is not None else defer_for(domain))


def dates_between(start: date, end: date, cap_days: int = 90) -> list[date]:
    """Inclusive day span for range-shaped payloads (device syncs, CSV uploads)."""
    if end < start:
        start, end = end, start
    span = min((end - start).days, cap_days - 1)
    return [start + timedelta(days=i) for i in range(span + 1)]


def contiguous_runs(days: list[date]) -> list[tuple[date, date]]:
    """Sorted (start, end) runs of consecutive days — lets a batch-shaped
    domain compute one window per run instead of per day, without a sparse
    cell set (e.g. a January edit + today) regenerating the months between."""
    runs: list[tuple[date, date]] = []
    for d in sorted(set(days)):
        if runs and (d - runs[-1][1]).days == 1:
            runs[-1] = (runs[-1][0], d)
        else:
            runs.append((d, d))
    return runs
