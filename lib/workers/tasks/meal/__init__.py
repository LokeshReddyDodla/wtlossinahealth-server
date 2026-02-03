"""Meal processing tasks."""

from lib.workers.tasks.meal.report_generation import generate_daily_meal_report
from lib.workers.tasks.meal.vector_generation import generate_meal_vector

__all__ = ["generate_daily_meal_report", "generate_meal_vector", "get_tasks"]


def get_tasks():
    """Return all meal tasks for ARQ worker."""
    return [generate_daily_meal_report, generate_meal_vector]
