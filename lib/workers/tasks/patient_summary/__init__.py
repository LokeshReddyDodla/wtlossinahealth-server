"""Patient summary ARQ tasks."""

from lib.workers.tasks.patient_summary.tasks import (
    generate_yesterdays_daily_summary,
    schedule_daily_patient_summaries,
    generate_daily_summary_for_patient,
    generate_summaries_for_date,
    regenerate_stale_summaries,
)

__all__ = [
    "generate_yesterdays_daily_summary",
    "schedule_daily_patient_summaries",
    "generate_daily_summary_for_patient",
    "generate_summaries_for_date",
    "regenerate_stale_summaries",
    "get_tasks",
    "get_cron_jobs",
]


def get_tasks():
    """Return all patient summary tasks for ARQ worker."""
    return [
        generate_yesterdays_daily_summary,
        schedule_daily_patient_summaries,
        generate_daily_summary_for_patient,
        generate_summaries_for_date,
        regenerate_stale_summaries,
    ]


def get_cron_jobs():
    """Return cron jobs for patient summary tasks."""
    from lib.workers.tasks.patient_summary.cron import (
        get_cron_jobs as _get_cron_jobs,
    )

    return _get_cron_jobs()
