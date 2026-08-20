"""Qdrant coverage reconciler — the correctness floor under the vector layer.

Qdrant is a rebuildable projection fed by an external paid API that can fail
silently (embedding credits, transport errors), so write paths are the fast
path and this sweep is the floor: diff source-of-truth ids against the points
that actually exist and enqueue only the missing work. Zero embedding spend
when coverage is complete — the diff is reads only.

Report vectors (cgm/sleep/fitness) reuse each domain's Mongo-vs-Qdrant
staleness filter; per-entity vectors (meal/smbg/manual vitals) are a presence
check on their deterministic point ids (md5 of the entity id) — edits already
re-vector at the write path, so only holes need filling here.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta
from typing import Any, Callable

from loguru import logger
from sqlalchemy.future import select

from lib.derived.domains.cgm import vector_windows
from lib.services.vector.utils.point_id_generator import PointIdGenerator
from lib.workers.arq.config import Queues
from lib.workers.arq.redis import enqueue_job
from lib.workers.tasks.base import TaskResult, task_with_logging

_BATCH = 20  # patients per invocation; the sweep self-re-enqueues the next page
_DEFAULT_WINDOW_DAYS = 120
_ID_CHUNK = 500
# Runaway guard: a patient needing more than this per type is a systemic
# outage — the capped remainder heals on the next weekly pass.
_MAX_ENQUEUES_PER_TYPE = 500


def normalize_point_id(point_id: Any) -> str:
    """Qdrant returns UUID-shaped ids (hyphenated) for the raw 32-hex md5 ids
    we store — comparing unnormalized would call every point missing and
    re-embed the world."""
    return str(point_id).replace("-", "").lower()


def diff_missing(candidates: list[tuple[str, Any]], existing_ids: set[str]) -> list[Any]:
    """candidates: (point_id, enqueue_thunk). Returns thunks for absent points."""
    return [
        thunk
        for point_id, thunk in candidates
        if normalize_point_id(point_id) not in existing_ids
    ]


def group_vital_rows(rows: list[dict]) -> dict[str, dict]:
    """ClickHouse long-format rows → per-vital_id payload dict in the shape
    the vitals vector task expects (one row per measured field)."""
    grouped: dict[str, dict] = {}
    for r in rows:
        vital = grouped.setdefault(
            r["vital_id"],
            {
                "test_time": r["time"],
                "source_name": r.get("source_name", ""),
                "source_platform": r.get("source_platform", ""),
                "uploaded_at": r["time"],
            },
        )
        vital[r["type"]] = r["value"]
    return grouped


async def _existing_point_ids(point_ids: list[str]) -> set[str]:
    from lib.core.container import container
    from lib.core.qdrant_store import QdrantStore

    store = container.resolve(QdrantStore)
    from lib.services.vector.utils.constants import DEFAULT_COLLECTION_NAME

    found: set[str] = set()
    async with store.get_client() as client:
        for i in range(0, len(point_ids), _ID_CHUNK):
            points = await client.retrieve(
                collection_name=DEFAULT_COLLECTION_NAME,
                ids=point_ids[i : i + _ID_CHUNK],
                with_payload=False,
                with_vectors=False,
            )
            found.update(normalize_point_id(p.id) for p in points)
    return found


# ── per-entity candidate builders: (point_id, enqueue_thunk) pairs ──────────


async def _meal_candidates(patient_id: str, since: datetime) -> list[tuple[str, Any]]:
    from lib.dependencies.database import postgres_store
    from lib.models.patient_meal import PatientMeal
    from lib.workers.tasks.meal.enqueue import enqueue_meal_vector_async

    async with postgres_store.get_session() as s:
        meal_ids = (
            (
                await s.execute(
                    select(PatientMeal.id).where(
                        PatientMeal.patient_id == patient_id,
                        PatientMeal.date >= since.date(),
                    )
                )
            )
            .scalars()
            .all()
        )

    def thunk(mid: str):
        return lambda: enqueue_meal_vector_async(patient_id, mid)

    return [
        (PointIdGenerator.generate_simple(str(mid)), thunk(str(mid)))
        for mid in meal_ids
    ]


async def _smbg_candidates(patient_id: str, since: datetime) -> list[tuple[str, Any]]:
    from lib.dependencies.database import postgres_store
    from lib.models.patient_smbg import PatientSMBG
    from lib.workers.tasks.smbg.enqueue import enqueue_generate_smbg_vector_async

    async with postgres_store.get_session() as s:
        rows = (
            (
                await s.execute(
                    select(PatientSMBG).where(
                        PatientSMBG.patient_id == patient_id,
                        PatientSMBG.reading_time >= since,
                    )
                )
            )
            .scalars()
            .all()
        )

    def thunk(r):
        reading_data = {
            "glucose_mgdl": r.glucose_level,
            "reading_time": r.reading_time.isoformat(),
            "type": r.type,
            "notes": r.notes,
            "uploaded_at": r.uploaded_at,
            "source": r.source_name or "app",
        }
        return lambda: enqueue_generate_smbg_vector_async(
            patient_id=patient_id, reading_id=str(r.id), reading_data=reading_data
        )

    return [(PointIdGenerator.generate_simple(str(r.id)), thunk(r)) for r in rows]


async def _vital_candidates(patient_id: str, since: datetime) -> list[tuple[str, Any]]:
    """Manual vitals only — device syncs write a rolling one-point-per-day
    snapshot that self-heals on the next sync."""
    from lib.core.clickhouse_store import canonical_vital_type
    from lib.core.container import container
    from lib.core.clickhouse_store import ClickHouseStore
    from lib.workers.tasks.vitals.enqueue import enqueue_generate_vital_vector_async

    store = container.resolve(ClickHouseStore)
    rows = await asyncio.to_thread(
        store.execute,
        """
        SELECT vital_id, type, value, time, source_name, source_platform
        FROM aihealth.vitals_data FINAL
        WHERE patient_id = %(pid)s AND time >= %(since)s AND vital_id != ''
        """,
        {"pid": patient_id, "since": since.replace(microsecond=0)},
    )
    grouped = group_vital_rows(
        [
            {
                "vital_id": r[0],
                "type": canonical_vital_type(r[1]),
                "value": r[2],
                "time": r[3],
                "source_name": r[4],
                "source_platform": r[5],
            }
            for r in rows
        ]
    )

    def thunk(vital_id: str, vital_data: dict):
        return lambda: enqueue_generate_vital_vector_async(
            patient_id=patient_id, vital_id=vital_id, vital_data=vital_data
        )

    return [
        (PointIdGenerator.generate_simple(vid), thunk(vid, data))
        for vid, data in grouped.items()
    ]


# Adding a type = one entry. The builder returns (point_id, enqueue_thunk)
# pairs for every entity that SHOULD have a vector in the window.
ENTITY_CANDIDATE_BUILDERS: dict[str, Callable] = {
    "meal": _meal_candidates,
    "smbg": _smbg_candidates,
    "vital": _vital_candidates,
}

# Report domains: (label, staleness filter module path, vector task name).
_REPORT_DOMAINS = (
    ("cgm", "lib.workers.tasks.cgm.vector_generation", "generate_cgm_vectors"),
    ("sleep", "lib.workers.tasks.sleep.vector_generation", "generate_sleep_vectors"),
    ("fitness", "lib.workers.tasks.fitness.vector_generation", "generate_fitness_vectors"),
)


async def _sweep_patient_reports(
    patient_id: str, window_days: int, stats: dict
) -> None:
    import importlib

    from lib.dependencies.service_dependencies import get_patient_profile_service

    end = datetime.now()
    start = end - timedelta(days=window_days)
    profile = None

    for label, module_path, task_name in _REPORT_DOMAINS:
        module = importlib.import_module(module_path)
        # CGM windows chunk to stay under the vectors job timeout; sleep and
        # fitness carry few points per day and fit one window.
        if label == "cgm":
            spans = vector_windows(
                [start.date() + timedelta(days=i) for i in range(window_days + 1)]
            )
        else:
            spans = [(start.date(), end.date())]

        for span_start, span_end in spans:
            s_dt = datetime.combine(span_start, time.min)
            e_dt = datetime.combine(span_end, time.max)
            missing = await module._filter_reports_needing_vectors(patient_id, s_dt, e_dt)
            if not missing:
                continue
            if profile is None:
                profile = await get_patient_profile_service().fetch_patient_profile(
                    patient_id
                )
                if not profile:
                    return
            await enqueue_job(
                task_name,
                patient_id,
                profile.age,
                profile.gender,
                s_dt,
                e_dt,
                _job_id=f"coverage:{label}:{patient_id}:{span_start}:{datetime.now():%Y%m%d%H%M%S}",
                _queue_name=Queues.VECTORS,
            )
            stats[f"reports_{label}"] = stats.get(f"reports_{label}", 0) + len(missing)


async def _sweep_patient_entities(
    patient_id: str, window_days: int, stats: dict
) -> None:
    since = datetime.now() - timedelta(days=window_days)
    for label, builder in ENTITY_CANDIDATE_BUILDERS.items():
        candidates = await builder(patient_id, since)
        if not candidates:
            continue
        existing = await _existing_point_ids([pid for pid, _ in candidates])
        missing = diff_missing(candidates, existing)
        if len(missing) > _MAX_ENQUEUES_PER_TYPE:
            logger.warning(
                f"[vector_coverage] {patient_id}/{label}: {len(missing)} missing, "
                f"capping at {_MAX_ENQUEUES_PER_TYPE} this pass"
            )
            missing = missing[:_MAX_ENQUEUES_PER_TYPE]
        for thunk in missing:
            await thunk()
        stats[f"entity_{label}"] = stats.get(f"entity_{label}", 0) + len(missing)


@task_with_logging
async def vector_coverage_sweep(
    ctx: dict[str, Any],
    window_days: int = _DEFAULT_WINDOW_DAYS,
    cursor: str | None = None,
    batch_size: int = _BATCH,
) -> TaskResult:
    from lib.dependencies.database import postgres_store
    from lib.models.patient import Patient

    async with postgres_store.get_session() as s:
        stmt = select(Patient.patient_id).order_by(Patient.patient_id).limit(batch_size)
        if cursor:
            stmt = stmt.where(Patient.patient_id > cursor)
        patient_ids = [str(pid) for pid in (await s.execute(stmt)).scalars().all()]

    if not patient_ids:
        return TaskResult(success=True, data={"done": True, "cursor": cursor})

    stats: dict[str, int] = {}
    for pid in patient_ids:
        # One bad patient must not kill the roster sweep.
        try:
            await _sweep_patient_reports(pid, window_days, stats)
            await _sweep_patient_entities(pid, window_days, stats)
        except Exception as e:
            logger.warning(f"[vector_coverage] sweep failed for {pid}: {e}")
            stats["patients_failed"] = stats.get("patients_failed", 0) + 1

    next_cursor = patient_ids[-1]
    await enqueue_job(
        "vector_coverage_sweep",
        window_days,
        next_cursor,
        batch_size,
        _job_id=f"vector:coverage:{next_cursor}:{datetime.now():%Y%m%d%H%M%S}",
        _queue_name=Queues.DEFAULT,
    )

    return TaskResult(
        success=True,
        data={"patients": len(patient_ids), "next_cursor": next_cursor, **stats},
    )
