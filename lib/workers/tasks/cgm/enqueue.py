"""Enqueue helpers for FastAPI endpoints and sync code."""

import asyncio
from typing import Dict, List, Optional

from loguru import logger


async def enqueue_cgm_report_generation_async(patient_id: str, periods: List[Dict]) -> Optional[str]:
    """Enqueue CGM report generation (async)."""
    from lib.workers.tasks.cgm.report_generation import enqueue_cgm_reports

    try:
        return await enqueue_cgm_reports(patient_id, periods)
    except Exception as e:
        logger.error(f"Failed to enqueue CGM reports for {patient_id}: {e}")
        return None


def enqueue_cgm_report_generation_sync(patient_id: str, periods: List[Dict]) -> Optional[str]:
    """Enqueue CGM report generation (sync)."""
    import nest_asyncio

    nest_asyncio.apply()

    loop = asyncio.get_event_loop()
    return loop.run_until_complete(enqueue_cgm_report_generation_async(patient_id, periods))
