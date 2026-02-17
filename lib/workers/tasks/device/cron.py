"""Scheduled cron jobs for device tasks."""

from lib.workers.tasks.device.deactivate_inactive import deactivate_inactive_devices
from lib.workers.tasks.utils import weekly_cron


def get_cron_jobs():
    """Return cron jobs for device tasks."""
    return [
        weekly_cron(
            coroutine=deactivate_inactive_devices,
            name="deactivate-inactive-devices",
            weekday=0,
            hour=2,
        ),
    ]
