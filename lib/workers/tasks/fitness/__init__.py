"""Fitness processing tasks."""

from lib.workers.tasks.fitness.report_generation import process_fitness_upload
from lib.workers.tasks.fitness.vector_generation import (
    generate_fitness_vectors,
    generate_fitness_vectors_batch,
)

__all__ = [
    "process_fitness_upload",
    "generate_fitness_vectors",
    "generate_fitness_vectors_batch",
    "get_tasks",
]


def get_tasks():
    """Return all fitness tasks for ARQ worker."""
    return [
        process_fitness_upload,
        generate_fitness_vectors,
        generate_fitness_vectors_batch,
    ]


def get_cron_jobs():
    """Return cron jobs for fitness tasks."""
    return []
