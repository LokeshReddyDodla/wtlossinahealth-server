from datetime import date, datetime
from typing import Optional
from loguru import logger

from lib.services.patient_summary.enum import StaleReason
from lib.dependencies.service_dependencies import get_patient_summary_service
from lib.workers.arq.redis import enqueue_job

async def mark_summary_stale_and_enqueue(
    patient_id: str,
    target_date: Optional[date] = None,
    stale_reason: StaleReason = StaleReason.DATA_UPDATED,
    force: bool = False,
) -> None:
    """
    Mark a patient's summary as stale and enqueue a summary generation job for today (or target_date).
    Deduplication is handled by ARQ job ID.
    """
    service = get_patient_summary_service()
    if target_date is None:
        target_date = datetime.now().date()
    await service.mark_summaries_as_stale(
        patient_id=patient_id,
        target_date=target_date,
        stale_reason=stale_reason,
    )
    job_id = f"summary:{patient_id}:{target_date.isoformat()}"
    try:
        await enqueue_job(
            "generate_daily_summary_for_patient",
            patient_id,
            target_date.isoformat(),
            force,
            _job_id=job_id,
        )
        logger.info(f"Enqueued summary job for {patient_id} on {target_date} (job_id={job_id})")
    except Exception as e:
        logger.warning(f"Failed to enqueue summary job for {patient_id} on {target_date}: {e}")
