"""Cron schedule for plan status reconciliation — nightly."""

from lib.workers.tasks.plans.reconcile import reconcile_plan_statuses
from lib.workers.tasks.utils.cron_helpers import daily_cron


def get_cron_jobs():
    """Nightly plan reconciliation at 00:30 worker timezone."""
    return [
        daily_cron(
            coroutine=reconcile_plan_statuses,
            name="plan-status-reconcile",
            hour=0,
            minute=30,
            timeout_s=600,
        ),
    ]
