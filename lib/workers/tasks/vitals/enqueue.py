"""Enqueue helpers for vitals tasks."""

import asyncio
from typing import Any, Dict, Optional

from loguru import logger

from lib.workers.tasks.vitals.vector_generation import _enqueue_vital_vector


async def enqueue_generate_vital_vector_async(
    patient_id: str,
    vital_id: str,
    vital_data: Dict[str, Any],
) -> Optional[str]:
    """Enqueue vital vector generation (async)."""
    try:
        return await _enqueue_vital_vector(patient_id, vital_id, vital_data)
    except Exception as e:
        logger.error(f"Failed to enqueue vital vector for {patient_id}: {e}")
        return None


def enqueue_generate_vital_vector_sync(
    patient_id: str,
    vital_id: str,
    vital_data: Dict[str, Any],
) -> Optional[str]:
    """Enqueue vital vector generation (sync)."""
    import nest_asyncio

    nest_asyncio.apply()
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(
        enqueue_generate_vital_vector_async(patient_id, vital_id, vital_data)
    )
