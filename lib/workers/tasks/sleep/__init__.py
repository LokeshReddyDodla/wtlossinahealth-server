"""Sleep processing tasks."""

from lib.workers.tasks.sleep.report_generation import process_sleep_upload
from lib.workers.tasks.sleep.vector_generation import generate_sleep_vectors

__all__ = [
    "process_sleep_upload",
    "generate_sleep_vectors",
    "get_tasks",
]


def get_tasks():
    """Return all sleep tasks for ARQ worker."""
    return [
        process_sleep_upload,
        generate_sleep_vectors,
    ]


def get_cron_jobs():
    """Return cron jobs for sleep tasks."""
    return []
