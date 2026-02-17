"""Enqueue helpers for package assignment tasks."""

import asyncio
from typing import Optional

from loguru import logger

from lib.workers.tasks.package.update_statuses import (
    _enqueue_update_package_assignment_statuses,
)


async def enqueue_update_package_assignment_statuses_async() -> Optional[str]:
    """Enqueue package assignment status update (async)."""
    try:
        return await _enqueue_update_package_assignment_statuses()
    except Exception as e:
        logger.error(f"Failed to enqueue package assignment status update: {e}")
        return None


def enqueue_update_package_assignment_statuses_sync() -> Optional[str]:
    """Enqueue package assignment status update (sync)."""
    import nest_asyncio

    nest_asyncio.apply()
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(
        enqueue_update_package_assignment_statuses_async()
    )
