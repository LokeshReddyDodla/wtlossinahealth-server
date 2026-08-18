"""Sleep Vector Generation Tasks — daily sleep reports → Qdrant."""

from datetime import datetime
from typing import Any

from loguru import logger

from lib.workers.arq.config import Queues
from lib.workers.arq.redis import enqueue_job
from lib.workers.tasks.base import TaskResult, task_with_logging


async def _filter_reports_needing_vectors(
    patient_id: str,
    start_date: datetime,
    end_date: datetime,
) -> list[dict]:
    """Daily reports whose vector is missing or older than the report."""
    from lib.dependencies.service_dependencies import (
        get_sleep_report_service,
        get_sleep_vector_service,
    )

    report_service = get_sleep_report_service()
    vector_service = get_sleep_vector_service()

    reports = await report_service.fetch_daily_reports_in_range(
        patient_id=patient_id,
        start_date=start_date.date(),
        end_date=end_date.date(),
        include_id=True,
    )

    if not reports:
        return []

    report_ids = [r["_id"] for r in reports]

    try:
        async with vector_service.qdrant_store.get_client() as client:
            from qdrant_client.http.models import (
                FieldCondition,
                Filter,
                MatchAny,
                MatchValue,
            )

            existing = await client.scroll(
                collection_name=vector_service.collection_name,
                scroll_filter=Filter(
                    must=[
                        FieldCondition(key="patient_id", match=MatchValue(value=patient_id)),
                        FieldCondition(key="report_id", match=MatchAny(any=report_ids)),
                    ]
                ),
                limit=10000,
                with_payload=True,
                with_vectors=False,
            )

        vector_updated_map: dict[str, Any] = {}
        for point in existing[0]:
            rid = point.payload.get("report_id")
            vec_updated = point.payload.get("vector_updated_at")
            if rid:
                if vec_updated is None:
                    vector_updated_map[rid] = None
                elif rid not in vector_updated_map or vec_updated > vector_updated_map[rid]:
                    vector_updated_map[rid] = vec_updated
    except Exception as e:
        logger.warning(
            f"Failed to query Qdrant for existing sleep vectors for {patient_id}: {e}. "
            "Will regenerate all vectors."
        )
        return reports

    from lib.utils.datetime_utils import parse_datetime

    needing: list[dict] = []
    for report in reports:
        rid = report["_id"]
        updated_at = report.get("updated_at")
        if isinstance(updated_at, str):
            updated_at = parse_datetime(updated_at)
        elif not isinstance(updated_at, datetime):
            updated_at = None

        if rid not in vector_updated_map or vector_updated_map[rid] is None or updated_at and int(updated_at.timestamp() * 1000) > vector_updated_map[rid]:
            needing.append(report)

    return needing


@task_with_logging
async def generate_sleep_vectors(
    ctx: dict[str, Any],
    patient_id: str,
    patient_age: int,
    patient_gender: str,
    start_date: datetime,
    end_date: datetime,
) -> TaskResult:
    """Generate sleep vector embeddings for daily reports in range."""
    try:
        from lib.dependencies.service_dependencies import (
            get_sleep_vector_service,
        )

        vector_service = get_sleep_vector_service()

        reports = await _filter_reports_needing_vectors(
            patient_id, start_date, end_date
        )

        if not reports:
            logger.info(f"All sleep vectors up to date for {patient_id}")
            return TaskResult(
                success=True,
                data={"patient_id": patient_id, "generated_count": 0,
                      "message": "all_up_to_date"},
            )

        await vector_service.upsert_report(
            patient_id, reports, patient_age, patient_gender
        )

        logger.info(
            f"Generated sleep vectors for {len(reports)} daily reports for {patient_id}"
        )

        return TaskResult(
            success=True,
            data={"patient_id": patient_id, "generated_count": len(reports),
                  "start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
        )

    except Exception as e:
        # Re-raise so arq retries: upsert is idempotent, and a swallowed failure
        # leaves the Qdrant point stale until the next sleep upload.
        logger.error(f"Failed to generate sleep vectors for {patient_id}: {e}")
        raise


async def _trigger_vector_generation(
    patient_id: str,
    start_date: datetime,
    end_date: datetime,
) -> None:
    """Trigger sleep vector generation after reports are generated."""
    try:
        from lib.dependencies.service_dependencies import (
            get_patient_profile_service,
        )

        patient = await get_patient_profile_service().fetch_patient_profile(patient_id)
        if not patient:
            logger.warning(f"Patient profile not found for {patient_id}")
            return

        vector_end = max(end_date, datetime.now())
        job_id = f"sleep_vector_generation_{patient_id}_{start_date.date()}_{vector_end.date()}"

        await enqueue_job(
            "generate_sleep_vectors",
            patient_id,
            patient.age,
            patient.gender,
            start_date,
            vector_end,
            _job_id=job_id,
            _queue_name=Queues.VECTORS,
        )

        logger.info(f"Triggered sleep vector generation for {patient_id}")

    except Exception as e:
        # Re-raise so the report task retries and re-enqueues: dedup by job_id.
        logger.error(f"Failed to trigger sleep vector generation for {patient_id}: {e}")
        raise
