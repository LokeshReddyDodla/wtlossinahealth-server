"""InBody ARQ tasks."""

from lib.workers.tasks.inbody.tasks import (
    generate_inbody_day_summary,
    schedule_inbody_day_summaries,
)

__all__ = [
    "generate_inbody_day_summary",
    "schedule_inbody_day_summaries",
    "get_tasks",
    "get_cron_jobs",
]


def get_tasks():
    """Return InBody tasks for the ARQ worker."""
    return [generate_inbody_day_summary, schedule_inbody_day_summaries]


def get_cron_jobs():
    """Return cron jobs for InBody tasks."""
    from lib.workers.tasks.inbody.cron import get_cron_jobs as _get_cron_jobs

    return _get_cron_jobs()
