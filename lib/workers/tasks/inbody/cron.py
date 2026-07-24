"""Scheduled cron jobs for InBody tasks."""

from lib.workers.tasks.inbody.tasks import schedule_inbody_day_summaries
from lib.workers.tasks.utils import daily_cron


def get_cron_jobs():
    """Return cron jobs for InBody tasks."""
    return [
        # End of day: fan out one day-summary job per InBody patient.
        daily_cron(
            coroutine=schedule_inbody_day_summaries,
            name="inbody-day-summary-daily",
            hour=22,
            minute=0,
            timeout_s=1800,
        ),
    ]
