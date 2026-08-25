"""Body Composition vector generation + proactive event tasks."""

from datetime import datetime
from typing import Any, Dict
from uuid import UUID

from loguru import logger

from lib.ai_foundation.agents.proactive_monitor.contracts import EventTrigger
from lib.workers.arq.config import Queues
from lib.workers.arq.redis import enqueue_job
from lib.workers.tasks.base import TaskResult, task_with_logging


@task_with_logging
async def generate_body_composition_vector(
    ctx: Dict[str, Any],
    patient_id: str,
    record_id: str,
) -> TaskResult:
    """Embed one confirmed body-composition scan, then wake the brain."""
    from lib.dependencies.service_dependencies import (
        get_body_composition_service,
        get_body_composition_vector_service,
        get_patient_profile_service,
    )

    try:
        service = get_body_composition_service()
        vector_service = get_body_composition_vector_service()
        patient_service = get_patient_profile_service()

        record = await service.get_record(UUID(patient_id), UUID(record_id))
        if record.get("status") != "confirmed":
            return TaskResult(
                success=False,
                error=f"Record not embeddable (status={record.get('status')})",
                data={"patient_id": patient_id, "record_id": record_id},
            )

        patient_profile = await patient_service.fetch_patient_profile(patient_id)
        if not patient_profile:
            logger.warning(f"Patient profile not found for {patient_id}")
            return TaskResult(
                success=False,
                error="Patient profile not found",
                data={"patient_id": patient_id, "record_id": record_id},
            )

        await vector_service.upsert_record(
            patient_id=patient_id,
            record_id=record_id,
            record=record,
            patient_age=patient_profile.age,
            patient_gender=patient_profile.gender,
        )
        logger.info(
            f"Generated body-composition vector for {patient_id} (record: {record_id})"
        )

        try:
            await enqueue_job(
                "handle_proactive_event",
                patient_id,
                EventTrigger.BODY_COMPOSITION_CONFIRMED.value,
                {
                    "record_id": record_id,
                    "event_time": record.get("test_datetime") or record.get("created_at"),
                },
                _job_id=f"insight:{EventTrigger.BODY_COMPOSITION_CONFIRMED.value}:{patient_id}:{record_id}",
                _defer_by=30,
                _queue_name=Queues.DEFAULT,
            )
        except Exception as exc:
            logger.warning(
                f"Failed to enqueue proactive event for body-composition {record_id} ({patient_id}): {exc}"
            )

        return TaskResult(
            success=True,
            data={"patient_id": patient_id, "record_id": record_id},
        )

    except Exception as e:
        logger.error(f"Failed to generate body-composition vector for {patient_id}: {e}")
        raise  # idempotent upsert — let arq retry transient failures


@task_with_logging
async def delete_body_composition_vector_task(
    ctx: Dict[str, Any],
    record_id: str,
) -> TaskResult:
    """Retryable Qdrant point delete."""
    from lib.dependencies.service_dependencies import (
        get_body_composition_vector_service,
    )

    try:
        await get_body_composition_vector_service().delete_record_vector(record_id)
        return TaskResult(success=True, data={"record_id": record_id})
    except Exception as e:
        logger.error(f"Failed to delete body-composition vector {record_id}: {e}")
        raise  # idempotent — let arq retry


async def enqueue_body_composition_vector(patient_id: str, record_id: str) -> str | None:
    """Enqueue vector generation for a confirmed body-composition record."""
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    job = await enqueue_job(
        "generate_body_composition_vector",
        patient_id,
        record_id,
        _job_id=f"body_composition:vector:{patient_id}:{record_id}:{timestamp}",
        _queue_name=Queues.VECTORS,
    )
    return job.job_id if job else None


async def enqueue_delete_body_composition_vector(record_id: str) -> str | None:
    """Enqueue vector deletion for an archived/superseded record."""
    job = await enqueue_job(
        "delete_body_composition_vector_task",
        record_id,
        _job_id=f"body_composition:vector:delete:{record_id}",
        _queue_name=Queues.VECTORS,
    )
    return job.job_id if job else None
