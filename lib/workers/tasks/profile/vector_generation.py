"""Profile Vector Generation Tasks."""

from datetime import datetime
from typing import Any, Dict

from loguru import logger

from lib.workers.arq.config import Queues
from lib.workers.arq.redis import enqueue_job
from lib.workers.tasks.base import TaskResult, task_with_logging


@task_with_logging
async def generate_profile_vector(
    ctx: Dict[str, Any],
    patient_id: str,
    profile_data: Dict[str, Any],
) -> TaskResult:
    """Generate and store profile vector embedding."""
    from lib.dependencies.service_dependencies import get_patient_profile_vector_service

    try:
        vector_service = get_patient_profile_vector_service()

        await vector_service.upsert_profile(profile_data)

        logger.info(f"Generated profile vector for {patient_id}")

        return TaskResult(
            success=True,
            data={"patient_id": patient_id},
        )

    except Exception as e:
        logger.error(f"Failed to generate profile vector for {patient_id}: {e}")
        return TaskResult(
            success=False,
            error=str(e),
            data={"patient_id": patient_id},
        )


async def _enqueue_profile_vector(
    patient_id: str, profile_data: Dict[str, Any]
) -> str | None:
    """Internal: Enqueue profile vector generation.

    The job_id is bucketed to the nearest minute so multiple PATCHes within
    that window collapse to a single embedding job (arq drops duplicates).
    A debounced chat-onboarding flow firing PATCH every ~1.5s costs us ~1-2
    embeddings per minute per patient instead of ~40.
    """
    minute_bucket = datetime.now().strftime("%Y%m%d%H%M")
    job_id = f"profile:vector:{patient_id}:{minute_bucket}"

    job = await enqueue_job(
        "generate_profile_vector",
        patient_id,
        profile_data,
        _job_id=job_id,
        _queue_name=Queues.VECTORS,
    )

    if job:
        logger.info(f"Enqueued profile vector generation for {patient_id}")
    else:
        logger.debug(f"Duplicate profile vector skipped: {job_id}")

    return job.job_id if job else None
