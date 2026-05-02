"""Scheduled cron jobs for LibreLinkUp live-polling sync."""

from lib.workers.tasks.librelink_up.sync import sync_all_patients_librelink_up
from lib.workers.tasks.utils import interval_cron


def get_cron_jobs():
    return [
        interval_cron(
            coroutine=sync_all_patients_librelink_up,
            name="librelinkup-sync-5min",
            minute_step=5,
            timeout_s=240,  # well under the 5-min interval
        ),
    ]
