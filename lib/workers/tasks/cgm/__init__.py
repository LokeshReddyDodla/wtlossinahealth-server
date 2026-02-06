"""CGM processing tasks."""

from lib.workers.tasks.cgm.report_generation import process_cgm_upload
from lib.workers.tasks.cgm.vector_generation import (
    generate_cgm_vectors,
    sync_all_daily_cgm_reports_to_vector_store,
)

__all__ = [
    "process_cgm_upload",
    "generate_cgm_vectors",
    "sync_all_daily_cgm_reports_to_vector_store",
    "get_tasks",
]


def get_tasks():
    """Return all CGM tasks for ARQ worker."""
    return [
        process_cgm_upload,
        generate_cgm_vectors,
        sync_all_daily_cgm_reports_to_vector_store,
    ]


def get_cron_jobs():
    """Return cron jobs for CGM tasks."""
    return []
