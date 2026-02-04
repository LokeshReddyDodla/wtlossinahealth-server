"""Package assignment processing tasks."""

from lib.workers.tasks.package.update_statuses import (
    update_package_assignment_statuses,
)

__all__ = [
    "update_package_assignment_statuses",
    "get_tasks",
]


def get_tasks():
    """Return all package assignment tasks for ARQ worker."""
    return [
        update_package_assignment_statuses,
    ]


def get_cron_jobs():
    """Return cron jobs for package assignment tasks."""
    from lib.workers.tasks.package.cron import get_cron_jobs as _get_cron_jobs

    return _get_cron_jobs()
