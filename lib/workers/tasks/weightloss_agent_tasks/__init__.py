"""Weightloss agent ARQ tasks."""

from lib.workers.tasks.weightloss_agent_tasks.tasks import (
    run_agentic_cycle,
    schedule_daily_agentic_cycles,
)

__all__ = [
    "run_agentic_cycle",
    "schedule_daily_agentic_cycles",
    "get_tasks",
    "get_cron_jobs",
]


def get_tasks():
    """Return all weightloss agent tasks for ARQ worker."""
    return [
        run_agentic_cycle,
        schedule_daily_agentic_cycles,
    ]


def get_cron_jobs():
    """Return cron jobs for weightloss agent tasks."""
    from lib.workers.tasks.weightloss_agent_tasks.cron import (
        get_cron_jobs as _get_cron_jobs,
    )

    return _get_cron_jobs()
