from datetime import date, datetime
from typing import Optional

from lib.services.patient_summary.enum import StaleReason


async def mark_summary_stale_and_enqueue(
    patient_id: str,
    target_date: Optional[date] = None,
    stale_reason: StaleReason = StaleReason.DATA_UPDATED,
    force: bool = False,
    enqueue: bool = True,
) -> Optional[str]:
    from lib.dependencies.service_dependencies import get_patient_summary_service
    from lib.workers.tasks.patient_summary.summary_generation import (
        _enqueue_patient_summary,
    )

    # service = get_patient_summary_service()
    # if target_date is None:
    #     target_date = datetime.now().date()

    # await service.mark_summaries_as_stale(
    #     patient_id=patient_id,
    #     target_date=target_date,
    #     stale_reason=stale_reason,
    # )

    # if enqueue:
    #     return await _enqueue_patient_summary(
    #         patient_id=patient_id, target_date=target_date, forced=force
    #     )
    
    return None
