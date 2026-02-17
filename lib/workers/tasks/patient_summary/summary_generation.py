"""Patient Summary Generation Tasks."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, Optional

from loguru import logger

from lib.services.patient_summary.enum import RegeneratedBy
from lib.workers.arq.config import Queues
from lib.workers.arq.redis import enqueue_job
from lib.workers.tasks.base import TaskResult, task_with_logging


@task_with_logging
async def generate_daily_summary_for_patient(
    ctx: Dict[str, Any],
    patient_id: str,
    target_date_str: str,
    forced: bool = False,
) -> TaskResult:
    """Generate daily patient summary for a specific date."""
    try:
        from lib.dependencies.service_dependencies import get_patient_summary_service

        target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
        service = get_patient_summary_service()
        await service.generate_daily_summary(
            patient_id=patient_id,
            target_date=target_date,
            regenerated_by=RegeneratedBy.SYSTEM,
            forced=forced,
        )
        logger.info(f"✅ Generated daily summary for {patient_id} on {target_date}")
        return TaskResult(
            success=True,
            data={"patient_id": patient_id, "target_date": target_date_str},
        )
    except Exception as e:
        logger.error(
            f"❌ Failed to generate daily summary for {patient_id} on {target_date_str}: {e}"
        )
        return TaskResult(
            success=False,
            error=str(e),
            data={"patient_id": patient_id, "target_date": target_date_str},
        )


@task_with_logging
async def regenerate_stale_summaries(ctx: Dict[str, Any]) -> TaskResult:
    """Regenerate all summaries marked as stale."""
    try:
        from lib.dependencies.service_dependencies import get_patient_summary_service

        service = get_patient_summary_service()
        stale_summaries = await service.get_stale_summaries()

        if not stale_summaries:
            logger.info("ℹ️ No stale summaries found")
            return TaskResult(
                success=True,
                data={"regenerated_count": 0, "failed_count": 0, "total": 0},
            )

        regenerated_count = 0
        failed_count = 0

        for summary in stale_summaries:
            try:
                patient_id = summary.get("patient_id")
                metadata = summary.get("metadata", {})
                date_range = metadata.get("date_range", {})
                date_str = date_range.get("start")

                if not patient_id or not date_str:
                    logger.warning(
                        f"⚠️ Skipping summary with missing patient_id or date: {summary.get('_id')}"
                    )
                    failed_count += 1
                    continue

                # Extract date from ISO format datetime string
                target_date = datetime.fromisoformat(date_str).date()

                await service.generate_daily_summary(
                    patient_id=patient_id,
                    target_date=target_date,
                    regenerated_by=RegeneratedBy.SYSTEM,
                    forced=True,
                )

                regenerated_count += 1
                logger.info(
                    f"✅ Regenerated stale summary for {patient_id} on {target_date}"
                )
            except Exception as e:
                failed_count += 1
                metadata = summary.get("metadata", {})
                date_range = metadata.get("date_range", {})
                logger.error(
                    f"❌ Failed to regenerate stale summary for {summary.get('patient_id')} "
                    f"on {date_range.get('start')}: {e}"
                )

        logger.info(
            f"✅ Regenerated {regenerated_count} stale summaries "
            f"({failed_count} failed out of {len(stale_summaries)} total)"
        )
        return TaskResult(
            success=True,
            data={
                "regenerated_count": regenerated_count,
                "failed_count": failed_count,
                "total": len(stale_summaries),
            },
        )
    except Exception as e:
        logger.error(f"❌ Failed to regenerate stale summaries: {e}")
        return TaskResult(
            success=False,
            error=str(e),
            data={"regenerated_count": 0, "failed_count": 0, "total": 0},
        )


async def _enqueue_patient_summary(
    patient_id: str,
    target_date: date,
    forced: bool = False,
) -> Optional[str]:
    """Internal: Enqueue patient summary generation."""
    target_date_str = target_date.isoformat()
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    job_id = f"summary:{patient_id}:{target_date_str}:{timestamp}"

    job = await enqueue_job(
        "generate_daily_summary_for_patient",
        patient_id,
        target_date_str,
        forced,
        _job_id=job_id,
        _queue_name=Queues.DEFAULT,
    )

    if job:
        logger.info(
            f"Enqueued summary generation for {patient_id} on {target_date_str}"
        )
    else:
        logger.debug(f"Duplicate summary generation skipped: {job_id}")

    return job.job_id if job else None
