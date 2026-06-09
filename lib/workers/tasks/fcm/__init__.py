"""FCM notification tasks."""

from lib.workers.tasks.fcm.broadcast import process_broadcast_notification
from lib.workers.tasks.fcm.notification import process_fcm_notification

__all__ = ["process_fcm_notification", "process_broadcast_notification", "get_tasks"]


def get_tasks():
    """Return all FCM tasks for ARQ worker."""
    return [process_fcm_notification, process_broadcast_notification]
