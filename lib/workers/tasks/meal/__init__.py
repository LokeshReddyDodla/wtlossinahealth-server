"""Meal processing tasks."""

from lib.workers.tasks.meal.report_generation import generate_daily_meal_report
from lib.workers.tasks.meal.vector_generation import delete_meal_vector_task, generate_meal_vector

__all__ = [
    "generate_daily_meal_report",
    "delete_meal_vector_task",
    "generate_meal_vector",
    "get_tasks",
    "get_cron_jobs",
]


def get_tasks():
    """Return all meal tasks for ARQ worker."""
    return [
        generate_daily_meal_report,
        delete_meal_vector_task,
        generate_meal_vector,
    ]


def get_cron_jobs():
    """Return cron jobs for meal tasks."""
    return []
