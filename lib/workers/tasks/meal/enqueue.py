"""Enqueue helpers for meal tasks."""

import asyncio
from datetime import date
from typing import Optional

from loguru import logger

from lib.workers.tasks.meal.report_generation import _enqueue_daily_meal_report
from lib.workers.tasks.meal.vector_generation import _enqueue_meal_vector


async def enqueue_daily_meal_report_async(
    patient_id: str, report_date: date, job_id: Optional[str] = None
) -> Optional[str]:
    """Enqueue daily meal report generation (async)."""
    try:
        return await _enqueue_daily_meal_report(patient_id, report_date, job_id)
    except Exception as e:
        logger.error(f"Failed to enqueue meal report for {patient_id}: {e}")
        return None


def enqueue_daily_meal_report_sync(patient_id: str, report_date: date) -> Optional[str]:
    """Enqueue daily meal report generation (sync)."""
    import nest_asyncio

    nest_asyncio.apply()
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(
        enqueue_daily_meal_report_async(patient_id, report_date)
    )


async def enqueue_meal_vector_async(
    patient_id: str, meal_id: str
) -> Optional[str]:
    """Enqueue meal vector generation (async)."""
    try:
        return await _enqueue_meal_vector(patient_id, meal_id)
    except Exception as e:
        logger.error(f"Failed to enqueue meal vector for {patient_id}: {e}")
        return None


def enqueue_meal_vector_sync(patient_id: str, meal_id: str) -> Optional[str]:
    """Enqueue meal vector generation (sync)."""
    import nest_asyncio

    nest_asyncio.apply()
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(
        enqueue_meal_vector_async(patient_id, meal_id)
    )
