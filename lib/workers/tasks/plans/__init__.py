"""Plan tasks — nightly diet/fitness plan status reconciliation."""

from lib.workers.tasks.plans.reconcile import reconcile_plan_statuses
from lib.workers.tasks.plans.cron import get_cron_jobs

__all__ = ["reconcile_plan_statuses", "get_tasks", "get_cron_jobs"]


def get_tasks():
    """Return all plan task functions for ARQ worker."""
    return [reconcile_plan_statuses]
