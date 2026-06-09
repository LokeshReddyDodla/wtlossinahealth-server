"""SMBG Vector Generation Tasks."""

from datetime import datetime
from typing import Any, Dict

from loguru import logger

from lib.ai_foundation.agents.proactive_monitor.contracts import EventTrigger
from lib.workers.arq.config import Queues
from lib.workers.arq.redis import enqueue_job
from lib.workers.tasks.base import TaskResult, task_with_logging


@task_with_logging
async def generate_smbg_vector(
    ctx: Dict[str, Any],
    patient_id: str,
    reading_id: str,
    reading_data: Dict[str, Any],
) -> TaskResult:
    """Generate and store SMBG vector embedding."""
    from lib.dependencies.service_dependencies import (
        get_patient_profile_service,
        get_smbg_vector_service,
    )

    try:
        vector_service = get_smbg_vector_service()
        patient_service = get_patient_profile_service()

        patient_profile = await patient_service.fetch_patient_profile(patient_id)
        if not patient_profile:
            logger.warning(f"Patient profile not found for {patient_id}")
            return TaskResult(
                success=False,
                error="Patient profile not found",
                data={"patient_id": patient_id, "reading_id": reading_id},
            )

        await vector_service.upsert_smbg(
            patient_id=patient_id,
            reading_id=reading_id,
            reading=reading_data,
            patient_age=patient_profile.age,
            patient_gender=patient_profile.gender,
        )

        logger.info(f"Generated SMBG vector for {patient_id} (reading: {reading_id})")

        try:
            await enqueue_job(
                "handle_proactive_event",
                patient_id,
                EventTrigger.SMBG_LOGGED.value,
                {"reading_id": reading_id},
                _job_id=f"insight:{EventTrigger.SMBG_LOGGED.value}:{patient_id}:{reading_id}",
                _defer_by=30,
                _queue_name=Queues.DEFAULT,
            )
        except Exception as exc:
            logger.warning(
                f"Failed to enqueue proactive event for SMBG {reading_id} ({patient_id}): {exc}"
            )

        return TaskResult(
            success=True,
            data={"patient_id": patient_id, "reading_id": reading_id},
        )

    except Exception as e:
        logger.error(f"Failed to generate SMBG vector for {patient_id}: {e}")
        return TaskResult(
            success=False,
            error=str(e),
            data={"patient_id": patient_id, "reading_id": reading_id},
        )


async def _enqueue_smbg_vector(
    patient_id: str,
    reading_id: str,
    reading_data: Dict[str, Any],
) -> str | None:
    """Internal: Enqueue SMBG vector generation."""
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    job_id = f"smbg:vector:{patient_id}:{reading_id}:{timestamp}"

    job = await enqueue_job(
        "generate_smbg_vector",
        patient_id,
        reading_id,
        reading_data,
        _job_id=job_id,
        _queue_name=Queues.VECTORS,
    )

    if job:
        logger.info(f"Enqueued SMBG vector generation for {patient_id} (reading: {reading_id})")
    else:
        logger.debug(f"Duplicate SMBG vector skipped: {job_id}")

    return job.job_id if job else None
