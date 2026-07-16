"""Scheduled cron jobs for weightloss agent tasks."""

from lib.workers.tasks.weightloss_agent_tasks.tasks import (
    schedule_daily_agentic_cycles,
    sweep_agentic_checkins,
)
from lib.workers.tasks.utils import daily_cron, interval_cron


def get_cron_jobs():
    """Return cron jobs for weightloss agent tasks."""
    return [
        # Midnight IST daily reset
        daily_cron(
            coroutine=schedule_daily_agentic_cycles,
            name="weightloss-agent-daily-cycle",
            hour=0,
            minute=0,
            timeout_s=3600,
        ),
        # Deliver due morning/evening coach messages at patient-local
        # checkpoint times regardless of chat activity.
        interval_cron(
            coroutine=sweep_agentic_checkins,
            name="weightloss-agent-checkin-sweep",
            minute_step=15,
            timeout_s=840,
        ),
    ]
