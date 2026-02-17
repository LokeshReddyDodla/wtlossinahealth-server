"""Scheduled cron jobs for patient summary tasks."""

from lib.workers.tasks.patient_summary.summary_generation import regenerate_stale_summaries
from lib.workers.tasks.utils import daily_cron


def get_cron_jobs():
    """Return cron jobs for patient summary tasks."""
    return [
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
