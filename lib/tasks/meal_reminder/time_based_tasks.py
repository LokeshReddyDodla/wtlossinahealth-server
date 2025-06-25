from celery import shared_task
import asyncio
from .utils import process_meal_reminder_for_type


@shared_task
def check_breakfast_reminders():
    asyncio.run(process_meal_reminder_for_type("breakfast"))


@shared_task
def check_lunch_reminders():
    asyncio.run(process_meal_reminder_for_type("lunch"))


@shared_task
def check_dinner_reminders():
    asyncio.run(process_meal_reminder_for_type("dinner"))
