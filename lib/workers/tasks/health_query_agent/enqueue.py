import asyncio
from typing import Optional

from loguru import logger

from lib.workers.tasks.health_query_agent.compaction import (
    _enqueue_health_query_compaction,
)


async def enqueue_health_query_compaction_async(
    thread_id: str,
    patient_id: Optional[str] = None,
) -> Optional[str]:
    try:
        return await _enqueue_health_query_compaction(thread_id, patient_id)
    except Exception as e:
        logger.error(f"Failed to enqueue health query compaction for {thread_id}: {e}")
        return None


def enqueue_health_query_compaction_sync(
    thread_id: str,
    patient_id: Optional[str] = None,
) -> Optional[str]:
    import nest_asyncio

    nest_asyncio.apply()
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(
        enqueue_health_query_compaction_async(thread_id, patient_id)
    )
