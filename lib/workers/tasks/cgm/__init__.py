"""CGM processing tasks."""

from lib.workers.tasks.cgm.reconcile import reconcile_cgm_vectors
from lib.workers.tasks.cgm.report_generation import process_cgm_upload
from lib.workers.tasks.cgm.vector_generation import (
    generate_cgm_vectors,
    sync_all_daily_cgm_reports_to_vector_store,
)

__all__ = [
    "process_cgm_upload",
    "generate_cgm_vectors",
    "sync_all_daily_cgm_reports_to_vector_store",
    "reconcile_cgm_vectors",
    "get_tasks",
    "get_cron_jobs",
]


def get_tasks():
    """Return all CGM tasks for ARQ worker."""
    return [
        process_cgm_upload,
        generate_cgm_vectors,
        sync_all_daily_cgm_reports_to_vector_store,
        reconcile_cgm_vectors,
    ]


def get_cron_jobs():
    """Return cron jobs for CGM tasks."""
    from lib.workers.tasks.utils.cron_helpers import interval_cron

    return [
        interval_cron(
            coroutine=reconcile_cgm_vectors,
            name="cgm-reconcile-vectors",
            minute_step=30,
            timeout_s=120,
        ),
    ]
