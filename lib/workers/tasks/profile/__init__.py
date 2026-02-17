"""Profile processing tasks."""

from lib.workers.tasks.profile.vector_generation import generate_profile_vector

__all__ = [
    "generate_profile_vector",
    "get_tasks",
]


def get_tasks():
    """Return all profile tasks for ARQ worker."""
    return [
        generate_profile_vector,
    ]
