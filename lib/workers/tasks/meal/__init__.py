"""Meal processing tasks."""

from lib.workers.tasks.meal.report_generation import generate_daily_meal_report
from lib.workers.tasks.meal.reminders import (
    check_breakfast_reminders,
    check_dinner_reminders,
    check_lunch_reminders,
    check_missed_meals_streaks,
)
from lib.workers.tasks.meal.vector_generation import generate_meal_vector

__all__ = [
    "generate_daily_meal_report",
    "generate_meal_vector",
    "check_breakfast_reminders",
    "check_lunch_reminders",
    "check_dinner_reminders",
    "check_missed_meals_streaks",
    "get_tasks",
    "get_cron_jobs",
]


def get_tasks():
    """Return all meal tasks for ARQ worker."""
    return [
        generate_daily_meal_report,
        generate_meal_vector,
        check_breakfast_reminders,
        check_lunch_reminders,
        check_dinner_reminders,
        check_missed_meals_streaks,
    ]


def get_cron_jobs():
    """Return cron jobs for meal tasks."""
    from lib.workers.tasks.meal.cron import get_cron_jobs as get_meal_cron_jobs

    return get_meal_cron_jobs()
