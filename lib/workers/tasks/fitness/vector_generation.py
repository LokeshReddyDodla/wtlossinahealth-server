"""Fitness Vector Generation Tasks - Optimized (No Cache Store)."""

from datetime import datetime
from typing import Any, Dict, List

from loguru import logger

from lib.workers.arq.config import Queues
from lib.workers.arq.redis import enqueue_job
from lib.workers.tasks.base import TaskResult, task_with_logging


async def _filter_reports_needing_vectors(
    patient_id: str,
    start_date: datetime,
    end_date: datetime,
) -> List[Dict]:
    """Get daily reports that need vector generation.

    Compares report.updated_at with vector.vector_updated_at to determine
    if vectors need regeneration. Also regenerates vectors missing vector_updated_at
    to backfill the new field.
    """
    from lib.dependencies.service_dependencies import (
        get_fitness_report_service,
        get_fitness_vector_service,
    )

    report_service = get_fitness_report_service()
    vector_service = get_fitness_vector_service()

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
                Filter,
                FieldCondition,
                MatchValue,
                MatchAny,
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
async def generate_fitness_vectors(
    ctx: Dict[str, Any],
    patient_id: str,
    patient_age: int,
    patient_gender: str,
    start_date: datetime,
    end_date: datetime,
) -> TaskResult:
    """Generate vector embeddings - optimized without cache store."""
    try:
        from lib.dependencies.service_dependencies import (
            get_fitness_vector_service,
        )

        vector_service = get_fitness_vector_service()

        reports = await _filter_reports_needing_vectors(
            patient_id, start_date, end_date
        )

        if not reports:
            logger.info(f"All fitness vectors up to date for {patient_id}")
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
            f"Generated vectors for {len(reports)} daily reports for {patient_id}"
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
        logger.error(f"Failed to generate fitness vectors for {patient_id}: {e}")
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

        job_id = f"fitness_vector_generation_{patient_id}_{start_date.date()}_{vector_end.date()}"

        await enqueue_job(
            "generate_fitness_vectors",
            patient_id,
            patient.age,
            patient.gender,
            start_date,
            vector_end,
            _job_id=job_id,
            _queue_name=Queues.VECTOR_SYNC,
        )

        logger.info(f"Triggered fitness vector generation for {patient_id}")

    except Exception as e:
        logger.error(f"Failed to trigger vector generation for {patient_id}: {e}")
