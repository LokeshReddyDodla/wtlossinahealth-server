"""Enqueue helpers for fitness tasks."""

import asyncio
from datetime import datetime
from typing import Optional

from loguru import logger

from lib.workers.tasks.fitness.report_generation import _enqueue_fitness_upload


async def enqueue_process_fitness_upload_async(
    patient_id: str, start_date: datetime, end_date: datetime
) -> Optional[str]:
    """Enqueue fitness upload processing (async)."""
    try:
        return await _enqueue_fitness_upload(patient_id, start_date, end_date)
    except Exception as e:
        logger.error(f"Failed to enqueue fitness upload processing: {e}")
        return None


def enqueue_process_fitness_upload_sync(
    patient_id: str, start_date: datetime, end_date: datetime
) -> Optional[str]:
    """Enqueue fitness upload processing (sync)."""
    import nest_asyncio

    nest_asyncio.apply()
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(
        enqueue_process_fitness_upload_async(patient_id, start_date, end_date)
    )


