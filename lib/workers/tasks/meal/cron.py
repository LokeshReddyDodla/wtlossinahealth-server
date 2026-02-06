"""Scheduled cron jobs for meal tasks."""

from lib.workers.tasks.meal.reminders import (
    check_breakfast_reminders,
    check_dinner_reminders,
    check_lunch_reminders,
    check_missed_meals_streaks,
)
from lib.workers.tasks.utils import daily_cron


def get_cron_jobs():
    """Return cron jobs for meal tasks."""
    return [
        daily_cron(
            coroutine=check_breakfast_reminders,
            name="meal-reminder-breakfast",
            hour=10,
            minute=30,
        ),
        daily_cron(
            coroutine=check_lunch_reminders,
            name="meal-reminder-lunch",
            hour=14,
            minute=30,
        ),
        daily_cron(
            coroutine=check_dinner_reminders,
            name="meal-reminder-dinner",
            hour=22,
            minute=30,
        ),
        daily_cron(
            coroutine=check_missed_meals_streaks,
            name="meal-reminder-missed-streak",
            hour=9,
            minute=15,
        ),
    ]
