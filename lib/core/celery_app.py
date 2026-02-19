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
        "weightloss-agent-daily-cycle": {
            "task": "lib.tasks.weightloss_agent.agentic_orchestrator.schedule_daily_agentic_cycles",
            "schedule": crontab(hour="0", minute="0"),  # Midnight IST daily reset
        },
        "weightloss-agent-flow-cycle": {
            "task": "lib.tasks.weightloss_agent.flow_scheduler.schedule_weightloss_agentic_flows",
            "schedule": crontab(minute="0", hour="*/2"),  # Every 2 hours so time-window nudges fire
            "options": {
                "expires": 60 * 60 * 2,  # 2 hours expiration
            },
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
    },
)


from lib.tasks.weightloss_agent.agentic_orchestrator import *
from lib.tasks.weightloss_agent.flow_scheduler import *
from lib.tasks.patient_summary_tasks import *
