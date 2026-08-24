from datetime import datetime, timezone
from typing import Any

from lib.services.patient_brief.service import PatientBriefService
from lib.workers.arq.config import Queues
from lib.workers.arq.redis import enqueue_job
from lib.workers.tasks.base import TaskResult, task_with_logging

_MAX_TRIES = 2


@task_with_logging
async def generate_patient_brief(
    ctx: dict[str, Any], patient_id: str
) -> TaskResult:
    service = None
    try:
        service = ctx["container"].resolve(PatientBriefService)
        brief = await service.regenerate(patient_id)
        return TaskResult(
            success=True,
            data={
                "patient_id": patient_id,
                "generated_at": brief["generated_at"].isoformat(),
            },
        )
    except Exception:
        if int(ctx.get("job_try", 1)) >= _MAX_TRIES:
            if service is not None:
                await service.mark_failed(patient_id)
            else:
                collection = ctx["container"].resolve(
                    "patient_briefs_collection"
                )
                await collection.update_one(
                    {"patient_id": patient_id},
                    {
                        "$set": {"failed_at": datetime.now(timezone.utc)},
                        "$unset": {"generation_started_at": ""},
                    },
                    upsert=True,
                )
        raise


async def enqueue_patient_brief(
    patient_id: str, *, requested_at: datetime
) -> str | None:
    bucket = int(requested_at.timestamp()) // 120
    job = await enqueue_job(
        "generate_patient_brief",
        patient_id,
        _job_id=f"patient-brief:{patient_id}:{bucket}",
        _queue_name=Queues.REPORTS,
    )
    return job.job_id if job else None
