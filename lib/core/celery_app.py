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
            # "schedule": crontab(
            #     minute="0", hour="7,9,11,13,15,17,19"
            # ),  # 7AM-7PM every 2h
            "schedule": crontab(
                minute="0", hour="*/2"
            ),  # Every 2 hours at :00
            "options": {
                "expires": 30 * 60,  # 30 minutes expiration
            },
        },
    },
)


from lib.tasks.cgm_tasks import *
from lib.tasks.fitness_tasks import *
from lib.tasks.meal_tasks import *
from lib.tasks.sleep_tasks import *
from lib.tasks.fcm_tasks import *
from lib.tasks.libreview_tasks import *
