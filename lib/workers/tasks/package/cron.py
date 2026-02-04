"""Scheduled cron jobs for package assignment tasks."""

from lib.workers.tasks.package.update_statuses import (
    update_package_assignment_statuses,
)
from lib.workers.tasks.utils.cron_helpers import daily_cron


def get_cron_jobs():
    """Return cron jobs for package assignment tasks."""
    return [
        daily_cron(
            coroutine=update_package_assignment_statuses,
            name="update-package-assignment-statuses",
            hour=1,
            minute=0,
        ),
    ]
