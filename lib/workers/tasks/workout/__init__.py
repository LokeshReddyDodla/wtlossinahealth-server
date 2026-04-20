"""Patient workout processing tasks."""

from lib.workers.tasks.workout.vector_generation import generate_workout_vector

__all__ = [
    "generate_workout_vector",
    "get_tasks",
]


def get_tasks():
    """Return all workout tasks for ARQ worker."""
    return [
        generate_workout_vector,
    ]
