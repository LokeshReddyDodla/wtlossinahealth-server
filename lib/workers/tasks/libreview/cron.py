"""Scheduled cron jobs for LibreView sync tasks."""

from lib.workers.tasks.libreview.sync import sync_all_patients_libreview
from lib.workers.tasks.utils import daily_cron


def get_cron_jobs():
    """Return cron jobs for LibreView sync tasks."""
    return [
        daily_cron(
            coroutine=sync_all_patients_libreview,
            name="libreview-sync-8am",
            hour=7,
            minute=0,
            timeout_s=3600,  # 1 hour timeout for syncing all patients
        ),
        daily_cron(
            coroutine=sync_all_patients_libreview,
            name="libreview-sync-11am",
            hour=10,
            minute=0,
            timeout_s=3600,
        ),
        daily_cron(
            coroutine=sync_all_patients_libreview,
            name="libreview-sync-6pm",
            hour=17,
            minute=0,
            timeout_s=3600,
        ),
    ]
