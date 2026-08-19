"""InBody Vector Generation Tasks."""

from datetime import date, datetime
from typing import Any, Dict
from uuid import UUID

from loguru import logger

from lib.workers.arq.config import Queues
from lib.workers.arq.redis import enqueue_job
from lib.workers.tasks.base import TaskResult, task_with_logging

# Only these report states carry a usable extraction to embed.
USABLE_REPORT_STATUSES = ("extracted", "needs_review")


@task_with_logging
async def generate_inbody_vector(
    ctx: Dict[str, Any],
    patient_id: str,
    report_id: str,
) -> TaskResult:
    """Generate and store the vector embedding for one InBody report."""
    from lib.dependencies.service_dependencies import (
        get_inbody_report_service,
        get_inbody_vector_service,
        get_patient_profile_service,
    )

    try:
        report_service = get_inbody_report_service()
        vector_service = get_inbody_vector_service()
        patient_service = get_patient_profile_service()

        report = await report_service.get_report_detail(
            UUID(patient_id), UUID(report_id)
        )

        if report.get("status") not in USABLE_REPORT_STATUSES or not report.get(
            "analysis"
        ):
            return TaskResult(
                success=False,
                error=f"Report not embeddable (status={report.get('status')})",
                data={"patient_id": patient_id, "report_id": report_id},
            )

        patient_profile = await patient_service.fetch_patient_profile(
            patient_id
        )
        if not patient_profile:
            logger.warning(f"Patient profile not found for {patient_id}")
            return TaskResult(
                success=False,
                error="Patient profile not found",
                data={"patient_id": patient_id, "report_id": report_id},
            )

        await vector_service.upsert_report(
            patient_id=patient_id,
            report_id=report_id,
            report_date=date.fromisoformat(report["report_date"]),
            analysis=report["analysis"],
            patient_age=patient_profile.age,
            patient_gender=patient_profile.gender,
            needs_review=report.get("status") == "needs_review",
        )

        logger.info(
            f"Generated InBody vector for {patient_id} (report: {report_id})"
        )

        return TaskResult(
            success=True,
            data={"patient_id": patient_id, "report_id": report_id},
        )

    except Exception as e:
        logger.error(
            f"Failed to generate InBody vector for {patient_id} "
            f"(report: {report_id}): {e}"
        )
        return TaskResult(
            success=False,
            error=str(e),
            data={"patient_id": patient_id, "report_id": report_id},
        )


async def _enqueue_inbody_vector(
    patient_id: str,
    report_id: str,
) -> str | None:
    """Internal: Enqueue InBody vector generation."""
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    job_id = f"inbody:vector:{report_id}:{timestamp}"

    job = await enqueue_job(
        "generate_inbody_vector",
        patient_id,
        report_id,
        _job_id=job_id,
        _queue_name=Queues.VECTORS,
    )

    if job:
        logger.info(
            f"Enqueued InBody vector generation for {patient_id} "
            f"(report: {report_id})"
        )
    else:
        logger.debug(f"Duplicate InBody vector job skipped: {job_id}")

    return job.job_id if job else None
