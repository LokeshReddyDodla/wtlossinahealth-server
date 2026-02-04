"""Enqueue helpers for SMBG tasks."""

import asyncio
from typing import Any, Dict, Optional

from loguru import logger

from lib.workers.tasks.smbg.vector_generation import _enqueue_smbg_vector


async def enqueue_generate_smbg_vector_async(
    patient_id: str,
    reading_id: str,
    reading_data: Dict[str, Any],
) -> Optional[str]:
    """Enqueue SMBG vector generation (async)."""
    try:
        return await _enqueue_smbg_vector(patient_id, reading_id, reading_data)
    except Exception as e:
        logger.error(f"Failed to enqueue SMBG vector for {patient_id}: {e}")
        return None


def enqueue_generate_smbg_vector_sync(
    patient_id: str,
    reading_id: str,
    reading_data: Dict[str, Any],
) -> Optional[str]:
    """Enqueue SMBG vector generation (sync)."""
    import nest_asyncio

    nest_asyncio.apply()
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(
        enqueue_generate_smbg_vector_async(patient_id, reading_id, reading_data)
    )
