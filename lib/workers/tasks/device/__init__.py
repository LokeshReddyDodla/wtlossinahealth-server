"""Device management tasks."""

from lib.workers.tasks.device.deactivate_inactive import deactivate_inactive_devices
from lib.workers.tasks.device.cron import get_cron_jobs
from lib.workers.tasks.device.enqueue import (
    enqueue_deactivate_inactive_devices_async,
    enqueue_deactivate_inactive_devices_sync,
)

__all__ = [
    "deactivate_inactive_devices",
    "get_tasks",
    "get_cron_jobs",
    "enqueue_deactivate_inactive_devices_async",
    "enqueue_deactivate_inactive_devices_sync",
]


def get_tasks():
    """Return all device tasks for ARQ worker."""
    return [deactivate_inactive_devices]
