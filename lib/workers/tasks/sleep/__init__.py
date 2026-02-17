"""Sleep processing tasks."""

from lib.workers.tasks.sleep.report_generation import process_sleep_upload

__all__ = [
    "process_sleep_upload",
    "get_tasks",
]


def get_tasks():
    """Return all sleep tasks for ARQ worker."""
    return [
        process_sleep_upload,
    ]


def get_cron_jobs():
    """Return cron jobs for sleep tasks."""
    return []
