"""Meal Vector Generation Tasks."""

from datetime import datetime
from typing import Any, Dict

from loguru import logger

from lib.ai_foundation.agents.proactive_monitor.contracts import EventTrigger
from lib.workers.arq.config import Queues
from lib.workers.arq.redis import enqueue_job
from lib.workers.tasks.base import TaskResult, task_with_logging


@task_with_logging
async def generate_meal_vector(
    ctx: Dict[str, Any],
    patient_id: str,
    meal_id: str,
    meal_data: Dict[str, Any],
) -> TaskResult:
    """Generate and store meal vector embedding."""
    from lib.dependencies.service_dependencies import (
        get_meal_vector_service,
        get_patient_profile_service,
    )

    try:
        vector_service = get_meal_vector_service()
        patient_service = get_patient_profile_service()

        patient_profile = await patient_service.fetch_patient_profile(patient_id)
        if not patient_profile:
            logger.warning(f"Patient profile not found for {patient_id}")
            return TaskResult(
                success=False,
                error="Patient profile not found",
                data={"patient_id": patient_id, "meal_id": meal_id},
            )

        await vector_service.upsert_meal(
            patient_id,
            meal_id,
            meal_data,
            patient_profile.age,
            patient_profile.gender,
        )

        logger.info(f"Generated meal vector for {patient_id} (meal: {meal_id})")

        # Event-driven proactive insight — deferred 30s for Qdrant indexing.
        try:
            # event_time = when the meal was CONSUMED (date + time from the
            # meal record) — retro-logged meals diverge from scan time.
            meal_event_time = None
            if meal_data.get("date") and meal_data.get("time"):
                meal_event_time = f"{meal_data['date']}T{meal_data['time']}"
            await enqueue_job(
                "handle_proactive_event",
                patient_id,
                EventTrigger.MEAL_LOGGED.value,
                {"meal_id": meal_id, "event_time": meal_event_time},
                _job_id=f"insight:{EventTrigger.MEAL_LOGGED.value}:{patient_id}:{meal_id}",
                _defer_by=30,
                _queue_name=Queues.DEFAULT,
            )
        except Exception as exc:
            logger.warning(
                f"Failed to enqueue proactive event for meal {meal_id} ({patient_id}): {exc}"
            )

        return TaskResult(
            success=True,
            data={"patient_id": patient_id, "meal_id": meal_id},
        )

    except Exception as e:
        # Re-raise so arq's retry machinery engages (retry_jobs/max_tries):
        # the upsert is idempotent, and this task is the only path that gets
        # the meal into Qdrant AND fires its proactive insight.
        logger.error(f"Failed to generate meal vector for {patient_id}: {e}")
        raise


@task_with_logging
async def delete_meal_vector_task(
    ctx: Dict[str, Any],
    meal_id: str,
) -> TaskResult:
    """Retryable Qdrant point delete — used when the inline delete after a
    Postgres meal delete fails, so the point can't survive as an orphan the
    agent keeps citing."""
    from lib.dependencies.service_dependencies import get_meal_vector_service

    try:
        await get_meal_vector_service().delete_meal_vector(meal_id)
        return TaskResult(success=True, data={"meal_id": meal_id})
    except Exception as e:
        logger.error(f"Failed to delete meal vector {meal_id}: {e}")
        raise  # idempotent — let arq retry


async def _enqueue_meal_vector(
    patient_id: str, meal_id: str, meal_data: Dict[str, Any]
) -> str | None:
    """Internal: Enqueue meal vector generation."""
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    job_id = f"meal:vector:{patient_id}:{meal_id}:{timestamp}"

    job = await enqueue_job(
        "generate_meal_vector",
        patient_id,
        meal_id,
        meal_data,
        _job_id=job_id,
        _queue_name=Queues.VECTORS,
    )

    if job:
        logger.info(f"Enqueued meal vector generation for {patient_id} (meal: {meal_id})")
    else:
        logger.debug(f"Duplicate meal vector skipped: {job_id}")

    return job.job_id if job else None
