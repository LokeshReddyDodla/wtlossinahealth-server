"""Cron schedule for re-engagement notifications — Tuesday + Friday at 10am."""

from lib.workers.tasks.reengagement.scan import run_reengagement_scan
from lib.workers.tasks.utils import weekly_cron


def get_cron_jobs():
    """Return cron jobs for re-engagement notifications.

    Runs at 10:00 AM worker timezone (Asia/Kolkata) on Tuesday and Friday.
    Weekday convention: 0=Sunday, 2=Tuesday, 5=Friday.
    """
    return [
        weekly_cron(
            coroutine=run_reengagement_scan,
            name="reengagement-tuesday",
            weekday=2,
            hour=10,
            timeout_s=600,
        ),
        weekly_cron(
            coroutine=run_reengagement_scan,
            name="reengagement-friday",
            weekday=5,
            hour=10,
            timeout_s=600,
        ),
    ]
