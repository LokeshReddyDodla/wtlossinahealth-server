"""CGM task definitions."""

from typing import Callable, List


def get_tasks() -> List[Callable]:
    """Get CGM task functions for ARQ worker."""
    from .report_generation import process_cgm_upload
    return [process_cgm_upload]


def get_cron_jobs() -> List:
    """Get scheduled CGM jobs (add cron jobs here when needed)."""
    return []


from .enqueue import enqueue_cgm_report_generation_async, enqueue_cgm_report_generation_sync

__all__ = [
    "get_tasks",
    "get_cron_jobs",
    "enqueue_cgm_report_generation_async",
    "enqueue_cgm_report_generation_sync",
]
