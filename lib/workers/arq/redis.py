"""Redis pool and job enqueue."""

import asyncio
from typing import Optional

from arq import create_pool
from arq.connections import ArqRedis
from loguru import logger

from .config import Queues, get_arq_redis_settings


class ArqRedisPool:
    _pool: Optional[ArqRedis] = None
    _lock: asyncio.Lock = asyncio.Lock()

    @classmethod
    async def get_pool(cls) -> ArqRedis:
        async with cls._lock:
            if cls._pool is None:
                # The pool's default queue must match WorkerSettings.queue_name.
                # arq's own default is "arq:queue", so without this every
                # enqueue_job() call that doesn't pass _queue_name lands on a
                # queue no worker polls, and the job waits forever.
                cls._pool = await create_pool(
                    get_arq_redis_settings(),
                    default_queue_name=Queues.DEFAULT,
                )
            return cls._pool

    @classmethod
    async def close_pool(cls) -> None:
        async with cls._lock:
            if cls._pool is not None:
                await cls._pool.close()
                cls._pool = None


async def get_arq_pool() -> ArqRedis:
    return await ArqRedisPool.get_pool()


async def enqueue_job(
    task_name: str,
    *args,
    _job_id: Optional[str] = None,
    _queue_name: Optional[str] = None,
    **kwargs,
):
    pool = await get_arq_pool()

    job = await pool.enqueue_job(
        task_name,
        *args,
        _job_id=_job_id,
        _queue_name=_queue_name,
        **kwargs,
    )

    if job is None:
        logger.debug(f"Duplicate job skipped: {_job_id}")
    else:
        logger.info(f"Enqueued: {task_name} (ID: {job.job_id})")

    return job


async def is_job_in_queue(job_id: str) -> bool:
    pool = await get_arq_pool()
    job_key = f"arq:job:{job_id}"
    exists = await pool.exists(job_key)
    return bool(exists)
