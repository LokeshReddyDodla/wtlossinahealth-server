"""Vitals Vector Generation Tasks."""

from datetime import datetime
from typing import Any, Dict

from loguru import logger

from lib.workers.arq.config import Queues
from lib.workers.arq.redis import enqueue_job
from lib.workers.tasks.base import TaskResult, task_with_logging


@task_with_logging
async def generate_vital_vector(
    ctx: Dict[str, Any],
    patient_id: str,
    vital_id: str,
    vital_data: Dict[str, Any],
) -> TaskResult:
    """Generate and store vital vector embedding."""
    from lib.dependencies.service_dependencies import (
        get_patient_profile_service,
        get_vitals_vector_service,
    )

    try:
        vector_service = get_vitals_vector_service()
        patient_service = get_patient_profile_service()

        patient_profile = await patient_service.fetch_patient_profile(patient_id)
        if not patient_profile:
            logger.warning(f"Patient profile not found for {patient_id}")
            return TaskResult(
                success=False,
                error="Patient profile not found",
                data={"patient_id": patient_id, "vital_id": vital_id},
            )

        await vector_service.upsert_vital(
            patient_id=patient_id,
            vital_id=vital_id,
            vital=vital_data,
            patient_age=patient_profile.age,
            patient_gender=patient_profile.gender,
        )

        logger.info(f"Generated vital vector for {patient_id} (vital: {vital_id})")

        return TaskResult(
            success=True,
            data={"patient_id": patient_id, "vital_id": vital_id},
        )

    except Exception as e:
        # Re-raise: the upsert is idempotent — let arq retry a transient
        # Qdrant/embedding failure instead of losing the vector permanently.
        logger.error(f"Failed to generate vital vector for {patient_id}: {e}")
        raise


async def _enqueue_vital_vector(
    patient_id: str,
    vital_id: str,
    vital_data: Dict[str, Any],
) -> str | None:
    """Internal: Enqueue vital vector generation."""
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    job_id = f"vital:vector:{patient_id}:{vital_id}:{timestamp}"

    job = await enqueue_job(
        "generate_vital_vector",
        patient_id,
        vital_id,
        vital_data,
        _job_id=job_id,
        _queue_name=Queues.VECTORS,
    )

    if job:
        logger.info(f"Enqueued vital vector generation for {patient_id} (vital: {vital_id})")
    else:
        logger.debug(f"Duplicate vital vector skipped: {job_id}")

    return job.job_id if job else None
