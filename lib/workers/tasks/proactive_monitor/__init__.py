"""Proactive Monitor tasks — background health scanning with cron scheduling."""

from lib.workers.tasks.proactive_monitor.scan import (
    run_proactive_scan,
    run_proactive_scan_single,
)
from lib.workers.tasks.proactive_monitor.cron import get_cron_jobs

__all__ = [
    "run_proactive_scan",
    "run_proactive_scan_single",
    "get_tasks",
    "get_cron_jobs",
]


def get_tasks():
    """Return all proactive monitor task functions for ARQ worker."""
    return [run_proactive_scan, run_proactive_scan_single]
