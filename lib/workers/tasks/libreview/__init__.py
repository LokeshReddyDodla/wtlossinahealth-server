"""LibreView sync tasks."""

from lib.workers.tasks.libreview.sync import sync_patient_libreview

__all__ = [
    "sync_patient_libreview",
    "get_tasks",
    "get_cron_jobs",
]


def get_tasks():
    """Return all LibreView tasks for ARQ worker."""
    return [
        sync_patient_libreview,
    ]


def get_cron_jobs():
    """Return cron jobs for LibreView tasks."""
    return []
