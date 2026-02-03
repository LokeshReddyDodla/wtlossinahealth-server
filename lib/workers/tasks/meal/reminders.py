"""Meal reminder tasks."""

from typing import Any, Dict

from loguru import logger

from lib.workers.tasks.base import TaskResult, task_with_logging
from lib.workers.tasks.meal.reminders_helpers import (
    process_meal_reminder_for_type,
    process_missed_meals_check,
)


@task_with_logging
async def check_breakfast_reminders(ctx: Dict[str, Any]) -> TaskResult:
    """Check and send breakfast reminders to patients."""
    try:
        await process_meal_reminder_for_type("breakfast")
        logger.info("✅ Processed breakfast reminders")
        return TaskResult(success=True, data={"meal_type": "breakfast"})
    except Exception as e:
        logger.error(f"❌ Failed to process breakfast reminders: {e}")
        return TaskResult(success=False, error=str(e), data={"meal_type": "breakfast"})


@task_with_logging
async def check_lunch_reminders(ctx: Dict[str, Any]) -> TaskResult:
    """Check and send lunch reminders to patients."""
    try:
        await process_meal_reminder_for_type("lunch")
        logger.info("✅ Processed lunch reminders")
        return TaskResult(success=True, data={"meal_type": "lunch"})
    except Exception as e:
        logger.error(f"❌ Failed to process lunch reminders: {e}")
        return TaskResult(success=False, error=str(e), data={"meal_type": "lunch"})


@task_with_logging
async def check_dinner_reminders(ctx: Dict[str, Any]) -> TaskResult:
    """Check and send dinner reminders to patients."""
    try:
        await process_meal_reminder_for_type("dinner")
        logger.info("✅ Processed dinner reminders")
        return TaskResult(success=True, data={"meal_type": "dinner"})
    except Exception as e:
        logger.error(f"❌ Failed to process dinner reminders: {e}")
        return TaskResult(success=False, error=str(e), data={"meal_type": "dinner"})


@task_with_logging
async def check_missed_meals_streaks(ctx: Dict[str, Any]) -> TaskResult:
    """Check and send reminders for missed meal streaks."""
    try:
        await process_missed_meals_check()
        logger.info("✅ Processed missed meals streak reminders")
        return TaskResult(success=True, data={"reminder_type": "missed_streaks"})
    except Exception as e:
        logger.error(f"❌ Failed to process missed meals streaks: {e}")
        return TaskResult(
            success=False, error=str(e), data={"reminder_type": "missed_streaks"}
        )
