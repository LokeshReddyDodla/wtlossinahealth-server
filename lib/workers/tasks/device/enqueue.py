"""Enqueue helpers for device tasks."""

import asyncio
from typing import Optional

from loguru import logger

from lib.workers.arq.config import Queues
from lib.workers.arq.redis import enqueue_job


async def enqueue_deactivate_inactive_devices_async() -> Optional[str]:
    """Enqueue device deactivation task (async)."""
    try:
        from datetime import datetime
        
        timestamp = datetime.now().strftime("%Y%m%d%H%M")
        job_id = f"device:deactivate:{timestamp}"
        
        job = await enqueue_job(
            "deactivate_inactive_devices",
            _job_id=job_id,
            _queue_name=Queues.DEFAULT,
        )
        
        if job:
            logger.info("Enqueued device deactivation task")
        else:
            logger.debug(f"Duplicate device deactivation skipped: {job_id}")
        
        return job.job_id if job else None
    except Exception as e:
        logger.error(f"Failed to enqueue device deactivation: {e}")
        return None


def enqueue_deactivate_inactive_devices_sync() -> Optional[str]:
    """Enqueue device deactivation task (sync)."""
    import nest_asyncio

    nest_asyncio.apply()
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(
        enqueue_deactivate_inactive_devices_async()
    )
