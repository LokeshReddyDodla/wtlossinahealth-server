"""CGM processing tasks."""

from lib.workers.tasks.cgm.report_generation import process_cgm_upload
from lib.workers.tasks.cgm.vector_generation import generate_cgm_vectors

__all__ = [
    "process_cgm_upload",
    "generate_cgm_vectors",
    "get_tasks",
]


def get_tasks():
    """Return all CGM tasks for ARQ worker."""
    return [
        process_cgm_upload,
        generate_cgm_vectors,
    ]


def get_cron_jobs():
    """Return cron jobs for CGM tasks."""
    return []
