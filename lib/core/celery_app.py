from datetime import timedelta
from celery import Celery
from decouple import config
from celery.schedules import crontab

celery = Celery(
    "aihealth",
    broker=config("CELERY_BROKER_URL", default="redis://localhost:6379/0"),
    backend=config("CELERY_RESULT_BACKEND", default="redis://localhost:6379/0"),
)

celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Kolkata",
    enable_utc=True,
    broker_connection_retry_on_startup=True,
    beat_schedule={
        # "sync-libreview-daily": {
        #     "task": "lib.tasks.libreview_tasks.sync_all_libreview",
        #     "schedule": crontab(
        #         minute="0", hour="8,11,18"
        #     ),  # Runs at 8:00, 11:00, and 18:00
        #     "options": {
        #         "expires": 60 * 60,  # 1 hour expiration
        #     },
        # },
        # "trigger-cgm-vector-upsert-daily": {
        #     "task": "lib.tasks.cgm_tasks.trigger_cgm_vector_upsert_for_all_patients",
        #     "schedule": crontab(minute="0", hour="1"),  # 1:00 AM every day
        #     "options": {
        #         "expires": 60 * 60,  # 1 hour expiration
        #     },
        # },
        # "meal-reminder-breakfast": {
        #     "task": "lib.tasks.meal_reminder.time_based_tasks.check_breakfast_reminders",
        #     "schedule": crontab(
        #         hour="10", minute="30"
        #     ),  # After breakfast window ends
        # },
        # "meal-reminder-lunch": {
        #     "task": "lib.tasks.meal_reminder.time_based_tasks.check_lunch_reminders",
        #     "schedule": crontab(
        #         hour="14", minute="30"
        #     ),  # After lunch window ends
        # },
        # "meal-reminder-dinner": {
        #     "task": "lib.tasks.meal_reminder.time_based_tasks.check_dinner_reminders",
        #     "schedule": crontab(
        #         hour="22", minute="30"
        #     ),  # After dinner window ends
        # },
        # "meal-reminder-missed-streak": {
        #     "task": "lib.tasks.meal_reminder.general_check_task.check_missed_meals_streaks",
        #     "schedule": crontab(hour="9", minute="15"),  # Once every morning
        # },
        "weightloss-agent-daily-cycle": {
            "task": "lib.tasks.weightloss_agent.agentic_orchestrator.schedule_daily_agentic_cycles",
            "schedule": crontab(hour="0", minute="0"),  # Midnight IST daily reset
        },
        "patient-daily-summaries": {
            "task": "lib.tasks.patient_summary_tasks.schedule_daily_patient_summaries",
            "schedule": crontab(hour="3", minute="0"),  # 3:00 AM IST daily
        },
        "regenerate-stale-summaries": {
            "task": "lib.tasks.patient_summary_tasks.regenerate_stale_summaries",
            "schedule": crontab(
                hour="0,3,6,9,12,15,18,21", minute="0"
            ),  # Every 3 hours at :00
            "options": {
                "expires": 60 * 60 * 2,  # 2 hours expiration
            },
        },
        # "update-package-assignment-statuses": {
        #     "task": "lib.tasks.package_assignment_tasks.update_package_assignment_statuses",
        #     "schedule": crontab(hour="1", minute="0"),  # 1:00 AM IST daily
        #     "options": {
        #         "expires": 60 * 60,  # 1 hour expiration
        #     },
        # },
        # "deactivate-inactive-devices": {
        #     "task": "lib.tasks.other_tasks.deactivate_inactive_devices",
        #     "schedule": crontab(day_of_week=0, hour="2", minute="0"),  # Sunday 2:00 AM IST weekly
        #     "options": {
        #         "expires": 60 * 60 * 2,  # 2 hours expiration
        #     },
        # },
    },
)


from lib.tasks.cgm_tasks import *
from lib.tasks.fitness_tasks import *
from lib.tasks.meal_tasks import *
from lib.tasks.sleep_tasks import *
from lib.tasks.fcm_tasks import *
from lib.tasks.libreview_tasks import *
from lib.tasks.other_tasks import *
from lib.tasks.meal_reminder.general_check_task import *
from lib.tasks.meal_reminder.time_based_tasks import *
from lib.tasks.weightloss_agent.agentic_orchestrator import *
from lib.tasks.patient_summary_tasks import *
from lib.tasks.package_assignment_tasks import *
