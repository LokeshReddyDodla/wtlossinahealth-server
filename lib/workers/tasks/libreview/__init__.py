"""LibreView sync tasks."""

from lib.workers.tasks.libreview.sync import (
    sync_all_patients_libreview,
    sync_patient_libreview,
)

__all__ = [
    "sync_patient_libreview",
    "sync_all_patients_libreview",
    "get_tasks",
    "get_cron_jobs",
]


def get_tasks():
    """Return all LibreView tasks for ARQ worker."""
    return [
        sync_patient_libreview,
        sync_all_patients_libreview,
    ]


def get_cron_jobs():
    """Return cron jobs for libreview tasks."""
    from lib.workers.tasks.libreview.cron import (
        get_cron_jobs as get_libreview_cron_jobs,
    )

    return get_libreview_cron_jobs()
