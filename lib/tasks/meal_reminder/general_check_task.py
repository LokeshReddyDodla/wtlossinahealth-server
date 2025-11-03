from celery import shared_task
from .utils import process_missed_meals_check


@shared_task(queue="default")
async def check_missed_meals_streaks():
    await process_missed_meals_check()
