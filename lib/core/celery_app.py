from datetime import timedelta
from celery import Celery
from decouple import config
from celery.schedules import crontab

celery = Celery(
    "aihealth",
    broker=config("CELERY_BROKER_URL", default="redis://localhost:6379/0"),
    backend=config(
        "CELERY_RESULT_BACKEND", default="redis://localhost:6379/0"
    ),
)

celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Kolkata",
    enable_utc=True,
    broker_connection_retry_on_startup=True,
    beat_schedule={
        "sync-libreview-every-2-hours": {
            "task": "lib.tasks.libreview_tasks.sync_all_libreview",
            "schedule": crontab(
                minute="0", hour="10,12,14,16,18"
            ),  # 10AM-6PM every 2h
            # "schedule": crontab(
            #     minute="0", hour="*/2"
            # ),  # Every 2 hours at :00
            "options": {
                "expires": 30 * 60,  # 30 minutes expiration
            },
        },
        "meal-reminder-breakfast": {
            "task": "lib.tasks.meal_reminder.time_based_tasks.check_breakfast_reminders",
            "schedule": crontab(
                hour="10", minute="30"
            ),  # After breakfast window ends
        },
        "meal-reminder-lunch": {
            "task": "lib.tasks.meal_reminder.time_based_tasks.check_lunch_reminders",
            "schedule": crontab(
                hour="14", minute="30"
            ),  # After lunch window ends
        },
        "meal-reminder-dinner": {
            "task": "lib.tasks.meal_reminder.time_based_tasks.check_dinner_reminders",
            "schedule": crontab(
                hour="22", minute="30"
            ),  # After dinner window ends
        },
        "meal-reminder-missed-streak": {
            "task": "lib.tasks.meal_reminder.general_check_task.check_missed_meals_streaks",
            "schedule": crontab(hour="9", minute="15"),  # Once every morning
        },
    },
)


from lib.tasks.cgm_tasks import *
from lib.tasks.fitness_tasks import *
from lib.tasks.meal_tasks import *
from lib.tasks.sleep_tasks import *
from lib.tasks.fcm_tasks import *
from lib.tasks.libreview_tasks import *
from lib.tasks.meal_reminder.general_check_task import *
from lib.tasks.meal_reminder.time_based_tasks import *
