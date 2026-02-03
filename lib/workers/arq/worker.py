"""ARQ Worker - run with: arq lib.workers.arq.worker.WorkerSettings"""

from datetime import timedelta
from typing import Any, Dict

from loguru import logger

from .config import Queues, get_arq_redis_settings
from lib.workers.tasks import get_all_tasks

# Load all tasks at module level
_all_tasks = get_all_tasks()


async def startup(ctx: Dict[str, Any]) -> None:
    logger.info("ARQ Worker starting...")
    from lib.core.container import container

    ctx["container"] = container


async def shutdown(ctx: Dict[str, Any]) -> None:
    logger.info("ARQ Worker shutting down...")
    from lib.workers.arq.redis import ArqRedisPool

    await ArqRedisPool.close_pool()


class WorkerSettings:
    """Default worker - listens to default queue."""

    redis_settings = get_arq_redis_settings()
    functions = _all_tasks
    cron_jobs = []
    on_startup = startup
    on_shutdown = shutdown
    queue_name = Queues.DEFAULT
    max_jobs = 100
    job_timeout = timedelta(minutes=10)
    keep_result = timedelta(hours=24)
    retry_jobs = True
    max_tries = 3


class CGMReportWorkerSettings(WorkerSettings):
    """CGM-specific worker with dedicated queue."""

    redis_settings = WorkerSettings.redis_settings
    functions = WorkerSettings.functions
    queue_name = Queues.CGM_REPORTS
    max_jobs = 50
    job_timeout = timedelta(minutes=15)


class VectorSyncWorkerSettings(WorkerSettings):
    """Vector sync worker."""

    redis_settings = WorkerSettings.redis_settings
    functions = WorkerSettings.functions
    queue_name = Queues.VECTOR_SYNC
    max_jobs = 20
    job_timeout = timedelta(minutes=20)
    max_tries = 2
