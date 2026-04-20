"""Enqueue helpers for workout tasks."""

import asyncio
from typing import Any, Dict, Optional

from loguru import logger

from lib.workers.tasks.workout.vector_generation import _enqueue_workout_vector


async def enqueue_generate_workout_vector_async(
    patient_id: str,
    workout_id: str,
    workout_data: Dict[str, Any],
) -> Optional[str]:
    """Enqueue workout vector generation (async)."""
    try:
        return await _enqueue_workout_vector(patient_id, workout_id, workout_data)
    except Exception as e:
        logger.error(f"Failed to enqueue workout vector for {patient_id}: {e}")
        return None


def enqueue_generate_workout_vector_sync(
    patient_id: str,
    workout_id: str,
    workout_data: Dict[str, Any],
) -> Optional[str]:
    """Enqueue workout vector generation (sync)."""
    import nest_asyncio

    nest_asyncio.apply()
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(
        enqueue_generate_workout_vector_async(patient_id, workout_id, workout_data)
    )
