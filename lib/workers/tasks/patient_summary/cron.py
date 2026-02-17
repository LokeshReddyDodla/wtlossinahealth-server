"""Scheduled cron jobs for patient summary tasks."""

from lib.workers.tasks.patient_summary.tasks import (
    schedule_daily_patient_summaries,
    regenerate_stale_summaries,
)
from lib.workers.tasks.utils import daily_cron


def get_cron_jobs():
    """Return cron jobs for patient summary tasks."""
    return [
        # Daily summaries at 3:00 AM IST
        daily_cron(
            coroutine=schedule_daily_patient_summaries,
            name="patient-daily-summaries",
            hour=3,
            minute=0,
            timeout_s=3600,
        ),
        # Regenerate stale summaries every 3 hours
        daily_cron(
            coroutine=regenerate_stale_summaries,
            name="regenerate-stale-summaries-0",
            hour=0,
            minute=0,
            timeout_s=7200,
        ),
        daily_cron(
            coroutine=regenerate_stale_summaries,
            name="regenerate-stale-summaries-3",
            hour=3,
            minute=0,
            timeout_s=7200,
        ),
        daily_cron(
            coroutine=regenerate_stale_summaries,
            name="regenerate-stale-summaries-6",
            hour=6,
            minute=0,
            timeout_s=7200,
        ),
        daily_cron(
            coroutine=regenerate_stale_summaries,
            name="regenerate-stale-summaries-9",
            hour=9,
            minute=0,
            timeout_s=7200,
        ),
        daily_cron(
            coroutine=regenerate_stale_summaries,
            name="regenerate-stale-summaries-12",
            hour=12,
            minute=0,
            timeout_s=7200,
        ),
        daily_cron(
            coroutine=regenerate_stale_summaries,
            name="regenerate-stale-summaries-15",
            hour=15,
            minute=0,
            timeout_s=7200,
        ),
        daily_cron(
            coroutine=regenerate_stale_summaries,
            name="regenerate-stale-summaries-18",
            hour=18,
            minute=0,
            timeout_s=7200,
        ),
        daily_cron(
            coroutine=regenerate_stale_summaries,
            name="regenerate-stale-summaries-21",
            hour=21,
            minute=0,
            timeout_s=7200,
        ),
    ]
