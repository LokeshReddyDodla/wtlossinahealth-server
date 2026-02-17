"""CGM Vector Generation Tasks - Optimized (No Cache Store)."""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from loguru import logger

from lib.workers.arq.config import Queues
from lib.workers.arq.redis import enqueue_job
from lib.workers.tasks.base import TaskResult, task_with_logging


async def _filter_reports_needing_vectors(
    patient_id: str,
    start_date: datetime,
    end_date: datetime,
) -> List[Dict]:
    """Get daily CGM reports that need vector generation.

    Compares report.updated_at with vector.vector_updated_at to determine
    if vectors need regeneration. Also regenerates vectors missing vector_updated_at
    to backfill the new field.
    """
    from lib.dependencies.service_dependencies import (
        get_cgm_report_service,
        get_cgm_vector_service,
    )

    report_service = get_cgm_report_service()
    vector_service = get_cgm_vector_service()

    reports = await report_service.fetch_daily_reports(
        patient_id=patient_id,
        start_date=start_date,
        end_date=end_date,
    )

    if not reports:
        return []

    report_ids = [r["_id"] for r in reports]

    try:
        async with vector_service.qdrant_store.get_client() as client:
            from qdrant_client.http.models import (
                Filter,
                FieldCondition,
                MatchAny,
                MatchValue,
            )

            existing_vectors_result = await client.scroll(
                collection_name=vector_service.collection_name,
                scroll_filter=Filter(
                    must=[
                        FieldCondition(
                            key="patient_id",
                            match=MatchValue(value=patient_id),
                        ),
                        FieldCondition(
                            key="report_id",
                            match=MatchAny(any=report_ids),
                        ),
                    ]
                ),
                limit=10000,
                with_payload=True,
                with_vectors=False,
            )

        vector_updated_map = {}
        for point in existing_vectors_result[0]:
            report_id = point.payload.get("report_id")
            vector_updated_at = point.payload.get("vector_updated_at")
            if report_id:
                if vector_updated_at is None:
                    vector_updated_map[report_id] = None
                else:
                    if (
                        report_id not in vector_updated_map
                        or vector_updated_at > vector_updated_map[report_id]
                    ):
                        vector_updated_map[report_id] = vector_updated_at

    except Exception as e:
        logger.warning(
            f"Failed to query Qdrant for existing vectors for {patient_id}: {e}. "
            "Will regenerate all vectors."
        )
        return reports

    from lib.utils.datetime_utils import parse_datetime

    reports_needing_vectors = []
    for report in reports:
        report_id = report["_id"]
        report_updated_at = report.get("updated_at")

        if isinstance(report_updated_at, str):
            report_updated_at = parse_datetime(report_updated_at)
        elif not isinstance(report_updated_at, datetime):
            report_updated_at = None

        if report_id not in vector_updated_map:
            reports_needing_vectors.append(report)
        elif vector_updated_map[report_id] is None:
            reports_needing_vectors.append(report)
        elif report_updated_at:
            vector_updated_at_ms = vector_updated_map[report_id]
            report_updated_at_ms = int(report_updated_at.timestamp() * 1000)

            if report_updated_at_ms > vector_updated_at_ms:
                reports_needing_vectors.append(report)

    return reports_needing_vectors


@task_with_logging
async def generate_cgm_vectors(
    ctx: Dict[str, Any],
    patient_id: str,
    patient_age: int,
    patient_gender: str,
    start_date: datetime,
    end_date: datetime,
) -> TaskResult:
    """Generate CGM vector embeddings - optimized without cache store."""
    try:
        from lib.dependencies.service_dependencies import (
            get_cgm_vector_service,
        )

        vector_service = get_cgm_vector_service()

        reports = await _filter_reports_needing_vectors(
            patient_id, start_date, end_date
        )

        if not reports:
            logger.info(f"All CGM vectors up to date for {patient_id}")
            return TaskResult(
                success=True,
                data={
                    "patient_id": patient_id,
                    "generated_count": 0,
                    "message": "all_up_to_date",
                },
            )

        await vector_service.upsert_report(
            patient_id,
            reports,
            patient_age,
            patient_gender,
        )

        logger.info(
            f"Generated vectors for {len(reports)} daily CGM reports for {patient_id}"
        )

        return TaskResult(
            success=True,
            data={
                "patient_id": patient_id,
                "generated_count": len(reports),
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            },
        )

    except Exception as e:
        logger.error(f"Failed to generate CGM vectors for {patient_id}: {e}")
        return TaskResult(
            success=False,
            error=str(e),
            data={
                "patient_id": patient_id,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            },
        )


async def _trigger_vector_generation(
    patient_id: str,
    start_date: datetime,
    end_date: datetime,
) -> None:
    """Trigger vector generation after reports are generated."""
    try:
        from lib.dependencies.service_dependencies import (
            get_patient_profile_service,
        )

        patient_service = get_patient_profile_service()

        patient = await patient_service.fetch_patient_profile(patient_id)
        if not patient:
            logger.warning(f"Patient profile not found for {patient_id}")
            return

        vector_end = max(end_date, datetime.now())

        job_id = (
            f"cgm_vector_generation_{patient_id}_"
            f"{start_date.date()}_{vector_end.date()}"
        )

        await enqueue_job(
            "generate_cgm_vectors",
            patient_id,
            patient.age,
            patient.gender,
            start_date,
            vector_end,
            _job_id=job_id,
            _queue_name=Queues.VECTORS,
        )

        logger.info(f"Triggered CGM vector generation for {patient_id}")

    except Exception as e:
        logger.error(f"Failed to trigger CGM vector generation for {patient_id}: {e}")


@task_with_logging
async def sync_all_daily_cgm_reports_to_vector_store(
    ctx: Dict[str, Any],
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    patient_batch_size: int = 200,
    cursor_patient_id: Optional[str] = None,
    limit_patients: Optional[int] = None,
) -> TaskResult:
    """
    Orchestrator: enqueue CGM daily-report vector generation for ALL patients.

    Designed for very large datasets (thousands -> lacs) by paging through
    patient_ids from MongoDB and fanning out per-patient ARQ jobs.

    Notes:
    - This does NOT generate reports; it only upserts vectors for existing daily reports.
    - Per-patient vector generation uses `generate_cgm_vectors` which already skips
      up-to-date vectors via Qdrant payload metadata.
    """
    from lib.dependencies.service_dependencies import get_cgm_report_service

    if patient_batch_size <= 0:
        return TaskResult(
            success=False,
            error="patient_batch_size must be > 0",
            data={"patient_batch_size": patient_batch_size},
        )

    report_service = get_cgm_report_service()
    coll = report_service.cgm_report_collection

    # Default window: sync everything we have
    effective_start = start_date or datetime(1970, 1, 1)
    # slight buffer so "today's" daily reports (which often end at 23:59:59) aren't excluded
    effective_end = end_date or (datetime.now() + timedelta(days=1))

    match: Dict[str, Any] = {
        "metadata.report_type": "daily",
        "metadata.date_range.start": {"$gte": effective_start.isoformat()},
        "metadata.date_range.end": {"$lte": effective_end.isoformat()},
    }

    pipeline: List[Dict[str, Any]] = [
        {"$match": match},
        {"$group": {"_id": "$patient_id"}},
    ]

    if cursor_patient_id:
        pipeline.append({"$match": {"_id": {"$gt": cursor_patient_id}}})

    pipeline.extend(
        [
            {"$sort": {"_id": 1}},
            {"$limit": patient_batch_size},
        ]
    )

    patient_ids: List[str] = []
    async for doc in coll.aggregate(pipeline, allowDiskUse=True):
        pid = doc.get("_id")
        if pid:
            patient_ids.append(str(pid))
            if limit_patients and len(patient_ids) >= limit_patients:
                break

    if not patient_ids:
        return TaskResult(
            success=True,
            data={
                "enqueued_patients": 0,
                "message": "no_patients_found",
                "cursor_patient_id": cursor_patient_id,
                "start_date": effective_start.isoformat(),
                "end_date": effective_end.isoformat(),
            },
        )

    enqueued = 0
    for patient_id in patient_ids:
        await _trigger_vector_generation(patient_id, effective_start, effective_end)
        enqueued += 1

    # If we fetched a full batch, enqueue the next page.
    next_cursor = patient_ids[-1]
    next_job_id = None
    if len(patient_ids) >= patient_batch_size and not limit_patients:
        next_job_id = (
            "cgm:vector:sync_all_daily:"
            f"{effective_start.date().isoformat()}:"
            f"{effective_end.date().isoformat()}:"
            f"{next_cursor}"
        )
        await enqueue_job(
            "sync_all_daily_cgm_reports_to_vector_store",
            effective_start,
            effective_end,
            patient_batch_size,
            next_cursor,
            None,
            _job_id=next_job_id,
            _queue_name=Queues.DEFAULT,
        )

    logger.info(
        f"Enqueued CGM daily vector sync for {enqueued} patients "
        f"(cursor={cursor_patient_id} -> next={next_cursor})"
    )

    return TaskResult(
        success=True,
        data={
            "enqueued_patients": enqueued,
            "batch_size": patient_batch_size,
            "cursor_patient_id": cursor_patient_id,
            "next_cursor_patient_id": next_cursor,
            "next_job_id": next_job_id,
            "start_date": effective_start.isoformat(),
            "end_date": effective_end.isoformat(),
        },
    )
