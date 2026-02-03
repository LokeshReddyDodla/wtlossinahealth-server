"""Enqueue helpers for FCM notifications."""

import asyncio
from typing import Any, Dict, List, Optional

from loguru import logger

from lib.workers.arq.config import Queues
from lib.workers.arq.redis import enqueue_job


async def enqueue_fcm_notification_async(
    participants: List[Dict], notification_info: Dict[str, Any]
) -> Optional[str]:
    """Enqueue FCM notification task (async)."""
    if not participants:
        logger.warning("No participants provided for FCM notification")
        return None

    try:
        job = await enqueue_job(
            "process_fcm_notification",
            participants,
            notification_info,
            _queue_name=Queues.DEFAULT,
        )

        if job:
            logger.info(
                f"Enqueued FCM notification for {len(participants)} participants"
            )

        return job.job_id if job else None

    except Exception as e:
        logger.error(f"Failed to enqueue FCM notification: {e}")
        return None


def enqueue_fcm_notification_sync(
    participants: List[Dict], notification_info: Dict[str, Any]
) -> Optional[str]:
    """Enqueue FCM notification task (sync)."""
    import nest_asyncio

    nest_asyncio.apply()

    loop = asyncio.get_event_loop()
    return loop.run_until_complete(
        enqueue_fcm_notification_async(participants, notification_info)
    )
