"""Workout vector generation tasks."""

from datetime import datetime
from typing import Any, Dict

from loguru import logger

from lib.workers.arq.config import Queues
from lib.workers.arq.redis import enqueue_job
from lib.workers.tasks.base import TaskResult, task_with_logging


@task_with_logging
async def generate_workout_vector(
    ctx: Dict[str, Any],
    patient_id: str,
    workout_id: str,
    workout_data: Dict[str, Any],
) -> TaskResult:
    """Generate and store a workout vector embedding."""
    from lib.dependencies.service_dependencies import (
        get_patient_profile_service,
        get_workout_vector_service,
    )

    try:
        vector_service = get_workout_vector_service()
        patient_service = get_patient_profile_service()

        patient_profile = await patient_service.fetch_patient_profile(patient_id)
        if not patient_profile:
            logger.warning(f"Patient profile not found for {patient_id}")
            return TaskResult(
                success=False,
                error="Patient profile not found",
                data={"patient_id": patient_id, "workout_id": workout_id},
            )

        await vector_service.upsert_workout(
            patient_id=patient_id,
            workout_id=workout_id,
            workout=workout_data,
            patient_age=patient_profile.age,
            patient_gender=patient_profile.gender,
        )

        logger.info(f"Generated workout vector for {patient_id} (workout: {workout_id})")

        return TaskResult(
            success=True,
            data={"patient_id": patient_id, "workout_id": workout_id},
        )

    except Exception as e:
        logger.error(f"Failed to generate workout vector for {patient_id}: {e}")
        return TaskResult(
            success=False,
            error=str(e),
            data={"patient_id": patient_id, "workout_id": workout_id},
        )


async def _enqueue_workout_vector(
    patient_id: str,
    workout_id: str,
    workout_data: Dict[str, Any],
) -> str | None:
    """Internal: Enqueue workout vector generation."""
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    job_id = f"workout:vector:{patient_id}:{workout_id}:{timestamp}"

    job = await enqueue_job(
        "generate_workout_vector",
        patient_id,
        workout_id,
        workout_data,
        _job_id=job_id,
        _queue_name=Queues.VECTORS,
    )

    if job:
        logger.info(
            f"Enqueued workout vector generation for {patient_id} (workout: {workout_id})"
        )
    else:
        logger.debug(f"Duplicate workout vector skipped: {job_id}")

    return job.job_id if job else None
