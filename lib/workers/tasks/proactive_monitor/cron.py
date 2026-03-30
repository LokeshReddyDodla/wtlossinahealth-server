"""Proactive Monitor cron jobs — scheduled health scans every 4 hours."""

from lib.workers.tasks.utils.cron_helpers import daily_cron
from lib.workers.tasks.proactive_monitor.scan import run_proactive_scan


def get_cron_jobs():
    """Return cron jobs for proactive health monitoring.

    Runs at 8am, 12pm, 4pm, 8pm in the worker's timezone (TZ=Asia/Kolkata).
    Each scan checks all active patients (active device in last 7 days).
    """
    return [
        daily_cron(
            coroutine=run_proactive_scan,
            name="proactive-scan-8am",
            hour=8,
            minute=0,
            timeout_s=3600,
        ),
        # daily_cron(
        #     coroutine=run_proactive_scan,
        #     name="proactive-scan-12pm",
        #     hour=12,
        #     minute=0,
        #     timeout_s=3600,
        # ),
        daily_cron(
            coroutine=run_proactive_scan,
            name="proactive-scan-4pm",
            hour=16,
            minute=0,
            timeout_s=3600,
        ),
        daily_cron(
            coroutine=run_proactive_scan,
            name="proactive-scan-8pm",
            hour=20,
            minute=0,
            timeout_s=3600,
        ),
    ]
