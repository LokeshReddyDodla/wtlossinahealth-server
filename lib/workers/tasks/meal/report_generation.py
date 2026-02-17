"""Meal Report Generation Tasks."""

from datetime import date, datetime
from typing import Any, Dict

from loguru import logger

from lib.workers.arq.config import Queues
from lib.workers.arq.redis import enqueue_job
from lib.workers.tasks.base import TaskResult, task_with_logging


@task_with_logging
async def generate_daily_meal_report(
    ctx: Dict[str, Any],
    patient_id: str,
    report_date: date,
) -> TaskResult:
    """Generate and save daily meal report for a patient."""
    from lib.dependencies.service_dependencies import (
        get_meal_report_service,
        get_meal_stats_processor,
    )

    try:
        processor = get_meal_stats_processor()
        service = get_meal_report_service()

        report = await processor.get_meal_report_by_date(patient_id, report_date)

        await service.save_report(
            patient_id,
            {
                "patient_id": patient_id,
                "report_type": "daily",
                **report.model_dump(),
            },
        )

        logger.info(f"Generated daily meal report for {patient_id} on {report_date}")

        return TaskResult(
            success=True,
            data={
                "patient_id": patient_id,
                "report_date": str(report_date),
            },
        )

    except Exception as e:
        logger.error(
            f"Failed to generate meal report for {patient_id} on {report_date}: {e}"
        )
        return TaskResult(
            success=False,
            error=str(e),
            data={"patient_id": patient_id, "report_date": str(report_date)},
        )


async def _enqueue_daily_meal_report(patient_id: str, report_date: date) -> str | None:
    """Internal: Enqueue daily meal report generation."""
    report_date_str = report_date.isoformat()
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    job_id = f"meal:report:{patient_id}:{report_date_str}:{timestamp}"

    job = await enqueue_job(
        "generate_daily_meal_report",
        patient_id,
        report_date,
        _job_id=job_id,
        _queue_name=Queues.REPORTS,
    )

    if job:
        logger.info(f"Enqueued daily meal report for {patient_id} on {report_date_str}")
    else:
        logger.debug(f"Duplicate meal report skipped: {job_id}")

    return job.job_id if job else None
