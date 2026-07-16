"""Weightloss agent ARQ tasks."""

from lib.workers.tasks.weightloss_agent_tasks.tasks import (
    run_agentic_cycle,
    run_daily_holistic_analysis,
    run_whole_person_summary,
    run_whole_person_summary_for_patient,
    schedule_daily_agentic_cycles,
    sweep_agentic_checkins,
)

__all__ = [
    "run_agentic_cycle",
    "run_daily_holistic_analysis",
    "run_whole_person_summary",
    "run_whole_person_summary_for_patient",
    "schedule_daily_agentic_cycles",
    "sweep_agentic_checkins",
    "get_tasks",
    "get_cron_jobs",
]


def get_tasks():
    """Return all weightloss agent tasks for ARQ worker."""
    return [
        run_agentic_cycle,
        run_daily_holistic_analysis,
        run_whole_person_summary,
        run_whole_person_summary_for_patient,
        schedule_daily_agentic_cycles,
        sweep_agentic_checkins,
    ]


def get_cron_jobs():
    """Return cron jobs for weightloss agent tasks."""
    from lib.workers.tasks.weightloss_agent_tasks.cron import (
        get_cron_jobs as _get_cron_jobs,
    )

    return _get_cron_jobs()
