from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from loguru import logger

from lib.workers.arq.config import Queues
from lib.workers.arq.redis import enqueue_job
from lib.workers.tasks.base import TaskResult, task_with_logging


@task_with_logging
async def export_patient_data(ctx: Dict[str, Any], export_id: str) -> TaskResult:
    from lib.dependencies.service_dependencies import get_patient_data_export_service

    service = get_patient_data_export_service()
    result = await service.process_export_job(export_id)
    if result.get("success"):
        return TaskResult(success=True, data=result)

    return TaskResult(success=False, error=result.get("error"), data=result)


@task_with_logging
async def cleanup_expired_patient_exports(ctx: Dict[str, Any]) -> TaskResult:
    from lib.dependencies.service_dependencies import get_patient_data_export_service

    service = get_patient_data_export_service()
    result = await service.expire_old_exports()
    return TaskResult(success=True, data=result)


async def _enqueue_patient_export(export_id: str) -> Optional[str]:
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    job_id = f"patient-export:{export_id}:{timestamp}"

    job = await enqueue_job(
        "export_patient_data",
        export_id,
        _job_id=job_id,
        _queue_name=Queues.REPORTS,
    )

    if job:
        logger.info("Enqueued patient export job for {}", export_id)
        return job.job_id

    logger.warning("Failed to enqueue patient export job for {}", export_id)
    return None
