"""Body Composition processing tasks."""

from lib.workers.tasks.body_composition.vector_generation import (
    delete_body_composition_vector_task,
    generate_body_composition_vector,
)

__all__ = [
    "delete_body_composition_vector_task",
    "generate_body_composition_vector",
    "get_tasks",
]


def get_tasks():
    """Return all body-composition tasks for ARQ worker."""
    return [
        delete_body_composition_vector_task,
        generate_body_composition_vector,
    ]
