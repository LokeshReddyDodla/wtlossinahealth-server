"""Enqueue helpers for patient summary tasks."""

import asyncio
from datetime import date
from typing import Optional

from loguru import logger

from lib.workers.tasks.patient_summary.summary_generation import _enqueue_patient_summary


async def enqueue_patient_summary_async(
    patient_id: str,
    target_date: Optional[date] = None,
    forced: bool = False,
) -> Optional[str]:
    """Enqueue patient summary generation (async)."""
    try:
        return await _enqueue_patient_summary(patient_id, target_date, forced)
    except Exception as e:
        logger.error(f"Failed to enqueue patient summary for {patient_id}: {e}")
        return None


def enqueue_patient_summary_sync(
    patient_id: str,
    target_date: Optional[date] = None,
    forced: bool = False,
) -> Optional[str]:
    """Enqueue patient summary generation (sync)."""
    import nest_asyncio

    nest_asyncio.apply()
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(
        enqueue_patient_summary_async(patient_id, target_date, forced)
    )
