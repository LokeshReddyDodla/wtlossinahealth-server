"""Enqueue helpers for LibreView sync tasks."""

import asyncio
from datetime import datetime
from typing import Optional

from loguru import logger

from lib.workers.arq.config import Queues
from lib.workers.arq.redis import enqueue_job


async def _enqueue_libreview_sync(patient_id: str) -> Optional[str]:
    """Internal helper to enqueue LibreView sync."""
    job_id = f"libreview:sync:{patient_id}:{datetime.now().strftime('%Y%m%d%H%M%S')}"
    
    try:
        job = await enqueue_job(
            "sync_patient_libreview",
            patient_id,
            _job_id=job_id,
            _queue_name=Queues.LIBREVIEW,
        )
        
        if job:
            logger.info(f"Enqueued LibreView sync for patient {patient_id} (job: {job_id})")
            return job.job_id
        else:
            logger.warning(f"Failed to enqueue LibreView sync for patient {patient_id}")
            return None
            
    except Exception as e:
        logger.error(f"Error enqueuing LibreView sync for patient {patient_id}: {e}")
        return None


async def enqueue_libreview_sync_async(patient_id: str) -> Optional[str]:
    """Enqueue LibreView sync (async)."""
    return await _enqueue_libreview_sync(patient_id)


def enqueue_libreview_sync_sync(patient_id: str) -> Optional[str]:
    """Enqueue LibreView sync (sync)."""
    import nest_asyncio
    
    nest_asyncio.apply()
    
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(enqueue_libreview_sync_async(patient_id))


__all__ = [
    "enqueue_libreview_sync_async",
    "enqueue_libreview_sync_sync",
]
