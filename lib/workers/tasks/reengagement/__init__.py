"""Re-engagement tasks — nudge inactive patients back to the app."""

from lib.workers.tasks.reengagement.scan import run_reengagement_scan
from lib.workers.tasks.reengagement.cron import get_cron_jobs

__all__ = ["run_reengagement_scan", "get_tasks", "get_cron_jobs"]


def get_tasks():
    """Return all re-engagement task functions for ARQ worker."""
    return [run_reengagement_scan]
