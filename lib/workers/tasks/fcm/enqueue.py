"""Enqueue helpers for FCM notifications."""

import asyncio
from typing import Any, Dict, List, Optional

from loguru import logger

from lib.workers.tasks.fcm.notification import _enqueue_fcm_notification


async def enqueue_fcm_notification_async(
    participants: List[Dict], notification_info: Dict[str, Any]
) -> Optional[str]:
    """Enqueue FCM notification task (async)."""
    try:
        return await _enqueue_fcm_notification(participants, notification_info)
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
