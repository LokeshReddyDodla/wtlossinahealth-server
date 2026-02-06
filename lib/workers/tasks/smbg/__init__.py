"""SMBG processing tasks."""

from lib.workers.tasks.smbg.vector_generation import generate_smbg_vector

__all__ = [
    "generate_smbg_vector",
    "get_tasks",
]


def get_tasks():
    """Return all SMBG tasks for ARQ worker."""
    return [
        generate_smbg_vector,
    ]
