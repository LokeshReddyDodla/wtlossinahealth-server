from __future__ import annotations

from typing import Any, Dict, Optional

from loguru import logger

from lib.workers.arq.config import Queues
from lib.workers.arq.redis import enqueue_job
from lib.workers.tasks.base import TaskResult, task_with_logging


@task_with_logging
async def compact_health_query_thread(
    ctx: Dict[str, Any],
    thread_id: str,
    patient_id: Optional[str] = None,
) -> TaskResult:
    try:
        from lib.dependencies.service_dependencies import get_health_query_agent_service

        service = get_health_query_agent_service()
        compaction = await service.compact_thread(
            thread_id=thread_id,
            patient_id=patient_id,
        )
        return TaskResult(
            success=True,
            data={
                "thread_id": thread_id,
                "patient_id": patient_id,
                "summary": compaction.summary if compaction else None,
            },
        )
    except Exception as e:
        logger.error(f"Failed to compact health query thread {thread_id}: {e}")
        return TaskResult(
            success=False,
            error=str(e),
            data={"thread_id": thread_id, "patient_id": patient_id},
        )


async def _enqueue_health_query_compaction(
    thread_id: str,
    patient_id: Optional[str] = None,
) -> Optional[str]:
    job_id = f"health-query-compaction:{thread_id}"
    job = await enqueue_job(
        "compact_health_query_thread",
        thread_id,
        patient_id,
        _job_id=job_id,
        _queue_name=Queues.INSTANT,
        _defer_by=5,
    )
    return job.job_id if job else None
