"""Enqueue helpers for sleep tasks."""

import asyncio
from datetime import datetime
from typing import Optional

from loguru import logger

from lib.workers.tasks.sleep.report_generation import _enqueue_sleep_upload


async def enqueue_process_sleep_upload_async(
    patient_id: str,
    start_date: datetime,
    end_date: datetime,
    job_id: Optional[str] = None,
) -> Optional[str]:
    """Enqueue sleep upload processing (async)."""
    try:
        return await _enqueue_sleep_upload(patient_id, start_date, end_date, job_id)
    except Exception as e:
        logger.error(f"Failed to enqueue sleep upload processing: {e}")
        return None


def enqueue_process_sleep_upload_sync(
    patient_id: str, start_date: datetime, end_date: datetime
) -> Optional[str]:
    """Enqueue sleep upload processing (sync)."""
    import nest_asyncio

    nest_asyncio.apply()
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(
        enqueue_process_sleep_upload_async(patient_id, start_date, end_date)
    )
