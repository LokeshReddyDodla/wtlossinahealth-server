"""SMBG processing tasks."""

from lib.workers.tasks.smbg.vector_generation import delete_smbg_vector_task, generate_smbg_vector

__all__ = [
    "delete_smbg_vector_task",
    "generate_smbg_vector",
    "get_tasks",
]


def get_tasks():
    """Return all SMBG tasks for ARQ worker."""
    return [
        delete_smbg_vector_task,
        generate_smbg_vector,
    ]
