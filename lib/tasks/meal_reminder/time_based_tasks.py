from celery import shared_task
from .utils import process_meal_reminder_for_type


@shared_task(queue="default")
async def check_breakfast_reminders():
    await process_meal_reminder_for_type("breakfast")


@shared_task(queue="default")
async def check_lunch_reminders():
    await process_meal_reminder_for_type("lunch")


@shared_task(queue="default")
async def check_dinner_reminders():
    await process_meal_reminder_for_type("dinner")
