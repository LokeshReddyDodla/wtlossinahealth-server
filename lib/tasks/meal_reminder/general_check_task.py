from celery import shared_task
import asyncio
from .utils import process_missed_meals_check


@shared_task
def check_missed_meals_streaks():
    asyncio.run(process_missed_meals_check())
