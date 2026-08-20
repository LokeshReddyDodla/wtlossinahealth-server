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


def report_gap_marks(
    source_days: set[date],
    daily_days: set[date],
    weekly_starts: set[date],
    monthly_starts: set[date],
    has_rollups: bool,
) -> set[date]:
    """Days to mark dirty so the drain regenerates missing reports.

    A missing daily marks its own day; a missing weekly/monthly (while its
    source days exist) marks the period's first day — the drain's rollup then
    regenerates the whole period, and the daily recompute it also triggers is
    an idempotent overwrite."""
    marks = source_days - daily_days
    if has_rollups and source_days:
        expected_mondays = {d - timedelta(days=d.weekday()) for d in source_days}
        marks |= expected_mondays - weekly_starts
        expected_firsts = {d.replace(day=1) for d in source_days}
        marks |= expected_firsts - monthly_starts
    return marks


def _doc_dates(docs: list[dict], by: str) -> set[date]:
    out: set[date] = set()
    for doc in docs:
        raw = (
            doc.get("date")
            if by == "date"
            else ((doc.get("metadata") or {}).get("date_range") or {}).get("start")
        )
        if raw:
            try:
                out.add(date.fromisoformat(str(raw)[:10]))
            except ValueError:
                continue
    return out


async def _report_doc_dates(
    collection, patient_id: str, since_iso: str, meal_shaped: bool
) -> tuple[set[date], set[date], set[date]]:
    """(daily days, weekly period starts, monthly period starts) present in Mongo."""
    if meal_shaped:
        docs = await collection.find(
            {"patient_id": patient_id, "date": {"$gte": since_iso[:10]}},
            {"date": 1},
        ).to_list(length=None)
        return _doc_dates(docs, "date"), set(), set()
    docs = await collection.find(
        {
            "patient_id": patient_id,
            "metadata.report_type": {"$in": ["daily", "weekly", "monthly"]},
            "metadata.date_range.start": {"$gte": since_iso},
        },
        {"metadata.report_type": 1, "metadata.date_range.start": 1},
    ).to_list(length=None)
    by_type: dict[str, list] = {"daily": [], "weekly": [], "monthly": []}
    for doc in docs:
        rtype = (doc.get("metadata") or {}).get("report_type")
        if rtype in by_type:
            by_type[rtype].append(doc)
    return (
        _doc_dates(by_type["daily"], "start"),
        _doc_dates(by_type["weekly"], "start"),
        _doc_dates(by_type["monthly"], "start"),
    )


async def _sweep_patient_report_gaps(
    patient_id: str, window_days: int, stats: dict
) -> None:
    """A missing report is an unmarked dirty cell: diff source-days against
    report-days and mark_dirty the gaps — the drain owns regeneration."""
    from lib.core.clickhouse_store import ClickHouseStore
    from lib.core.container import container
    from lib.dependencies.database import postgres_store
    from lib.dependencies.service_dependencies import (
        get_cgm_report_service,
        get_fitness_report_service,
        get_meal_report_service,
        get_sleep_report_service,
    )
    from lib.derived import DataDomain, mark_dirty
    from lib.models.patient_meal import PatientMeal
    from lib.models.sleep_checkin import SleepCheckin

    since_dt = datetime.now() - timedelta(days=window_days)
    since_iso = since_dt.strftime("%Y-%m-%dT00:00:00")
    ch = container.resolve(ClickHouseStore)

    async def ch_days(query: str) -> set[date]:
        rows = await asyncio.to_thread(
            ch.execute, query, {"pid": patient_id, "since": since_dt.replace(microsecond=0)}
        )
        return {r[0] for r in rows}

    async with postgres_store.get_session() as s:
        meal_days = set(
            (
                await s.execute(
                    select(PatientMeal.date)
                    .where(
                        PatientMeal.patient_id == patient_id,
                        PatientMeal.date >= since_dt.date(),
                    )
                    .distinct()
                )
            )
            .scalars()
            .all()
        )
        checkin_days = set(
            (
                await s.execute(
                    select(SleepCheckin.checkin_date)
                    .where(
                        SleepCheckin.patient_id == patient_id,
                        SleepCheckin.checkin_date >= since_dt.date(),
                    )
                    .distinct()
                )
            )
            .scalars()
            .all()
        )

    domains = (
        (
            DataDomain.MEAL,
            meal_days,
            get_meal_report_service().meal_report_collection,
            True,
            False,
        ),
        (
            DataDomain.CGM,
            await ch_days(
                "SELECT DISTINCT toDate(time) FROM aihealth.cgm_data FINAL"
                " WHERE patient_id = %(pid)s AND record_type = 'historic'"
                " AND time >= %(since)s"
            ),
            get_cgm_report_service().cgm_report_collection,
            False,
            True,
        ),
        (
            DataDomain.SLEEP,
            await ch_days(
                "SELECT DISTINCT toDate(sleep_start_time) FROM aihealth.sleep_data FINAL"
                " WHERE patient_id = %(pid)s AND sleep_start_time >= %(since)s"
            )
            | checkin_days,
            get_sleep_report_service().sleep_report_collection,
            False,
            True,
        ),
        (
            DataDomain.FITNESS,
            await ch_days(
                "SELECT DISTINCT toDate(start_datetime) FROM aihealth.fitness_data FINAL"
                " WHERE patient_id = %(pid)s AND start_datetime >= %(since)s"
            ),
            get_fitness_report_service().fitness_report_collection,
            False,
            True,
        ),
    )

    for domain, source_days, collection, meal_shaped, has_rollups in domains:
        if not source_days:
            continue
        daily, weekly, monthly = await _report_doc_dates(
            collection, patient_id, since_iso, meal_shaped
        )
        marks = report_gap_marks(source_days, daily, weekly, monthly, has_rollups)
        if marks:
            await mark_dirty(patient_id, domain, sorted(marks))
            stats[f"report_gap_{domain.value}"] = (
                stats.get(f"report_gap_{domain.value}", 0) + len(marks)
            )


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


async def _workout_candidates(patient_id: str, since: datetime) -> list[tuple[str, Any]]:
    from lib.dependencies.service_dependencies import get_patient_workout_service
    from lib.workers.tasks.workout.enqueue import enqueue_generate_workout_vector_async

    listing = await get_patient_workout_service().list(
        patient_id, start_date=since.date(), end_date=date.today(), limit=1000
    )

    def thunk(w):
        return lambda: enqueue_generate_workout_vector_async(
            patient_id=patient_id,
            workout_id=str(w.id),
            workout_data=w.model_dump(mode="json"),
        )

    return [
        (PointIdGenerator.generate_simple(str(w.id)), thunk(w)) for w in listing.items
    ]


async def _medication_candidates(patient_id: str, since: datetime) -> list[tuple[str, Any]]:
    """One composite point per patient covering all medications."""
    from sqlalchemy import func as sa_func

    from lib.dependencies.database import postgres_store
    from lib.dependencies.service_dependencies import get_medication_service
    from lib.models.patient_medication import PatientMedication

    async with postgres_store.get_session() as s:
        count = (
            await s.execute(
                select(sa_func.count()).where(PatientMedication.patient_id == patient_id)
            )
        ).scalar_one()
    if not count:
        return []

    async def thunk():
        async with postgres_store.get_session() as session:
            await get_medication_service()._sync_qdrant(patient_id, session)

    return [(PointIdGenerator.generate_simple(f"{patient_id}_medications"), thunk)]


async def _plan_candidates(patient_id: str, since: datetime) -> list[tuple[str, Any]]:
    from lib.dependencies.service_dependencies import (
        get_patient_diet_plan_service,
        get_patient_fitness_plan_service,
    )

    diet_svc = get_patient_diet_plan_service()
    fitness_svc = get_patient_fitness_plan_service()
    out: list[tuple[str, Any]] = []

    for plan in await diet_svc.get_patient_diet_plans(patient_id):
        def diet_thunk(p=plan):
            return diet_svc._vectorize_diet_plan(p)

        out.append((PointIdGenerator.generate_simple(str(plan.diet_plan_id)), diet_thunk))
    for plan in await fitness_svc.get_patient_fitness_plans(patient_id):
        def fitness_thunk(p=plan):
            return fitness_svc._vectorize_fitness_plan(p)

        out.append(
            (PointIdGenerator.generate_simple(str(plan.fitness_plan_id)), fitness_thunk)
        )
    return out


async def _checkin_candidates(patient_id: str, since: datetime) -> list[tuple[str, Any]]:
    from lib.dependencies.service_dependencies import get_daily_checkin_service

    svc = get_daily_checkin_service()
    vec = svc.checkin_vector_service
    age, gender = await svc._demographics(patient_id)
    out: list[tuple[str, Any]] = []

    sleep_rows, _ = await svc.get_sleep_history(
        patient_id, since.date(), date.today(), limit=1000, offset=0
    )
    for r in sleep_rows:
        # One point per patient-day; composite id matches _build_sleep_point.
        dt = datetime.combine(r.checkin_date, time.min)
        point_id = PointIdGenerator.generate(
            patient_id, "sleep_checkin", dt, dt
        )

        def sleep_thunk(row=r):
            return vec.upsert_sleep_vector(
                patient_id=patient_id,
                sleep_data={
                    "checkin_date": str(row.checkin_date),
                    "quality": row.quality,
                    "hours_slept": row.hours_slept,
                    "bed_time": row.bed_time,
                    "wake_time": row.wake_time,
                    "notes": row.notes,
                },
                patient_age=age,
                patient_gender=gender,
            )

        out.append((point_id, sleep_thunk))

    mood_rows, _ = await svc.get_mood_history(
        patient_id, since.date(), date.today(), limit=1000, offset=0
    )
    for r in mood_rows:
        def mood_thunk(row=r):
            return vec.upsert_mood_vector(
                patient_id=patient_id,
                mood_entry_id=str(row.id),
                mood_data={
                    "level": row.level,
                    "emoji": row.emoji,
                    "tags": row.tags,
                    "notes": row.notes,
                    "recorded_at": row.recorded_at,
                },
                patient_age=age,
                patient_gender=gender,
            )

        out.append((PointIdGenerator.generate_simple(str(r.id)), mood_thunk))

    symptom_rows, _ = await svc.get_symptom_history(
        patient_id, since.date(), date.today(), limit=1000, offset=0
    )
    for r in symptom_rows:
        def symptom_thunk(row=r):
            return vec.upsert_symptom_vector(
                patient_id=patient_id,
                symptom_entry_id=str(row.id),
                symptom_data={
                    "recorded_at": row.recorded_at,
                    "notes": row.notes,
                    "symptoms": [
                        {
                            "symptom_name": i.symptom_name,
                            "severity": i.severity,
                            "custom_label": i.custom_label,
                        }
                        for i in (row.items or [])
                    ],
                },
                patient_age=age,
                patient_gender=gender,
            )

        out.append((PointIdGenerator.generate_simple(str(r.id)), symptom_thunk))

    return out


async def _profile_candidates(patient_id: str, since: datetime) -> list[tuple[str, Any]]:
    from lib.dependencies.service_dependencies import get_patient_profile_service
    from lib.schemas.patient import CorePatientProfile
    from lib.workers.tasks.profile.enqueue import enqueue_generate_profile_vector_async

    async def thunk():
        patient = await get_patient_profile_service().fetch_patient_profile(
            patient_id, detailed=True
        )
        if not patient:
            return None
        return await enqueue_generate_profile_vector_async(
            patient_id, CorePatientProfile.from_orm(patient).model_dump(mode="json")
        )

    return [(PointIdGenerator.generate_simple(str(patient_id)), thunk)]


async def _document_candidates(patient_id: str, since: datetime) -> list[tuple[str, Any]]:
    """text_repr/summary_text are persisted, so re-embedding costs no LLM calls."""
    from lib.dependencies.service_dependencies import (
        get_patient_document_service,
        get_patient_documents_collection,
        get_patient_profile_service,
    )

    docs = await get_patient_documents_collection().find(
        {"patient_id": patient_id, "metadata.created_at": {"$gte": since}},
    ).to_list(length=None)
    docs = [d for d in docs if d.get("text_repr")]
    if not docs:
        return []

    svc = get_patient_document_service()

    async def make_thunk(doc):
        profile = await get_patient_profile_service().fetch_patient_profile(patient_id)
        if not profile:
            return None
        payload = svc._build_embedding_payload(
            profile,
            str(doc["_id"]),
            doc["file"]["url"],
            doc["file"]["name"],
            doc["file"]["type"],
            doc.get("category"),
            doc.get("summary_text", ""),
            doc["text_repr"],
            doc["metadata"]["uploaded_by"]["id"],
            doc["metadata"]["uploaded_by"]["type"],
            doc["metadata"]["document_date"],
        )
        await svc._upsert_to_qdrant(payload, doc["text_repr"], str(doc["_id"]))

    def thunk(doc):
        return lambda: make_thunk(doc)

    return [
        (PointIdGenerator.generate_simple(str(d["_id"])), thunk(d)) for d in docs
    ]


# Adding a type = one entry. The builder returns (point_id, enqueue_thunk)
# pairs for every entity that SHOULD have a vector in the window.
ENTITY_CANDIDATE_BUILDERS: dict[str, Callable] = {
    "meal": _meal_candidates,
    "smbg": _smbg_candidates,
    "vital": _vital_candidates,
    "workout": _workout_candidates,
    "medication": _medication_candidates,
    "plans": _plan_candidates,
    "checkin": _checkin_candidates,
    "profile": _profile_candidates,
    "document": _document_candidates,
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
            await _sweep_patient_report_gaps(pid, window_days, stats)
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
