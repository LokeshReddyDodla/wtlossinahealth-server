"""Vitals processing tasks."""

from lib.workers.tasks.vitals.vector_generation import generate_vital_vector

__all__ = [
    "generate_vital_vector",
    "get_tasks",
]


def get_tasks():
    """Return all vitals tasks for ARQ worker."""
    return [
        generate_vital_vector,
    ]
