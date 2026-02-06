"""Enqueue helpers for profile tasks."""

import asyncio
from typing import Any, Dict, Optional

from loguru import logger

from lib.workers.tasks.profile.vector_generation import _enqueue_profile_vector


async def enqueue_generate_profile_vector_async(
    patient_id: str, profile_data: Dict[str, Any]
) -> Optional[str]:
    """Enqueue profile vector generation (async)."""
    try:
        return await _enqueue_profile_vector(patient_id, profile_data)
    except Exception as e:
        logger.error(f"Failed to enqueue profile vector for {patient_id}: {e}")
        return None


def enqueue_generate_profile_vector_sync(
    patient_id: str, profile_data: Dict[str, Any]
) -> Optional[str]:
    """Enqueue profile vector generation (sync)."""
    import nest_asyncio

    nest_asyncio.apply()
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(
        enqueue_generate_profile_vector_async(patient_id, profile_data)
    )
