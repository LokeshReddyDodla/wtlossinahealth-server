"""ARQ Worker - run with: arq lib.workers.arq.worker.WorkerSettings"""

from datetime import timedelta
from typing import Any, Dict

from loguru import logger

from .config import Queues, get_arq_redis_settings
from lib.workers.tasks import get_all_tasks

# Load all tasks at module level
_all_tasks = get_all_tasks()


def _get_all_cron_jobs():
    """Aggregate cron jobs from all task modules."""
    cron_jobs = []

    from lib.workers.tasks.device import get_cron_jobs as get_device_cron_jobs
    from lib.workers.tasks.libreview import get_cron_jobs as get_libreview_cron_jobs
    from lib.workers.tasks.meal import get_cron_jobs as get_meal_cron_jobs
    from lib.workers.tasks.package import get_cron_jobs as get_package_cron_jobs
    from lib.workers.tasks.patient_summary import get_cron_jobs as get_patient_summary_cron_jobs
    from lib.workers.tasks.weightloss_agent_tasks import get_cron_jobs as get_weightloss_agent_cron_jobs

    cron_jobs.extend(get_device_cron_jobs())
    cron_jobs.extend(get_libreview_cron_jobs())
    cron_jobs.extend(get_meal_cron_jobs())
    cron_jobs.extend(get_package_cron_jobs())
    cron_jobs.extend(get_patient_summary_cron_jobs())
    cron_jobs.extend(get_weightloss_agent_cron_jobs())

    return cron_jobs


async def startup(ctx: Dict[str, Any]) -> None:
    logger.info("ARQ Worker starting...")
    from lib.core.container import container

    ctx["container"] = container


async def shutdown(ctx: Dict[str, Any]) -> None:
    logger.info("ARQ Worker shutting down...")
    from lib.workers.arq.redis import ArqRedisPool

    await ArqRedisPool.close_pool()


class WorkerSettings:
    """Default worker - lightweight tasks."""

    redis_settings = get_arq_redis_settings()
    functions = _all_tasks
    cron_jobs = _get_all_cron_jobs()
    on_startup = startup
    on_shutdown = shutdown
    queue_name = Queues.DEFAULT
    max_jobs = 200
    job_timeout = timedelta(minutes=2)
    keep_result = timedelta(hours=24)
    retry_jobs = True
    max_tries = 3


class ReportsWorkerSettings(WorkerSettings):
    """Reports worker - report generation tasks."""

    redis_settings = WorkerSettings.redis_settings
    functions = WorkerSettings.functions
    queue_name = Queues.REPORTS
    max_jobs = 50
    job_timeout = timedelta(minutes=15)
    max_tries = 2


class VectorsWorkerSettings(WorkerSettings):
    """Vectors worker - vector generation tasks."""

    redis_settings = WorkerSettings.redis_settings
    functions = WorkerSettings.functions
    queue_name = Queues.VECTORS
    max_jobs = 30
    job_timeout = timedelta(minutes=20)
    max_tries = 2


class LibreViewWorkerSettings(WorkerSettings):
    """LibreView worker - LibreView sync tasks."""

    redis_settings = WorkerSettings.redis_settings
    functions = WorkerSettings.functions
    queue_name = Queues.LIBREVIEW
    max_jobs = 2
    job_timeout = timedelta(minutes=15)
    max_tries = 2
    keep_result = timedelta(seconds=0)
