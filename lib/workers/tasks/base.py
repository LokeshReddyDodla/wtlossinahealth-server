"""Task utilities."""

import functools
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, TypeVar

from loguru import logger

T = TypeVar("T")


class TaskResult:
    def __init__(self, success: bool, data: Any = None, error: Optional[str] = None):
        self.success = success
        self.data = data
        self.error = error


async def _persist_task_run(ctx, task_name, job_id, success, duration_ms, data, error):
    """Best-effort persist to MongoDB. Never raises."""
    try:
        container = ctx.get("container")
        if not container:
            return
        from lib.core.mongo_store import MongoStore

        mongo: MongoStore = container.resolve(MongoStore)
        col = mongo.get_collection("task_runs")
        await col.insert_one({
            "task_name": task_name,
            "job_id": job_id,
            "status": "ok" if success else "error",
            "duration_ms": round(duration_ms),
            "error": str(error)[:500] if error else None,
            "data": data if isinstance(data, dict) else None,
            "created_at": datetime.now(timezone.utc),
        })
    except Exception as exc:
        logger.debug("task_persist_failed task=%s error=%s", task_name, exc)


def task_with_logging(func: Callable[..., T]) -> Callable[..., T]:
    @functools.wraps(func)
    async def wrapper(ctx: Dict[str, Any], *args, **kwargs) -> T:
        task_name = func.__name__
        job_id = ctx.get("job_id", "unknown")

        logger.info(f"[{task_name}] Starting {job_id}")
        start_time = time.perf_counter()

        try:
            result = await func(ctx, *args, **kwargs)
            duration = (time.perf_counter() - start_time) * 1000
            logger.info(f"[{task_name}] Done {job_id} in {duration:.0f}ms")

            success = True
            error_msg = None
            data = None
            if isinstance(result, TaskResult):
                success = result.success
                error_msg = result.error
                data = result.data

            await _persist_task_run(ctx, task_name, job_id, success, duration, data, error_msg)
            return result
        except Exception as e:
            duration = (time.perf_counter() - start_time) * 1000
            logger.error(f"[{task_name}] Failed {job_id}: {e}")
            await _persist_task_run(ctx, task_name, job_id, False, duration, None, str(e))
            raise

    return wrapper
