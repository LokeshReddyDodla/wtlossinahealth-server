from celery import Celery
from decouple import config

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
)


from lib.tasks.fcm_tasks import send_fcm_notification_task
from lib.tasks.fitness_tasks import *
from lib.tasks.meal_tasks import *
