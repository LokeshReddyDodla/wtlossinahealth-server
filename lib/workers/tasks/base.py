"""Task utilities."""

import functools
import time
from typing import Any, Callable, Dict, Optional, TypeVar

from loguru import logger

T = TypeVar("T")


class TaskResult:
    def __init__(self, success: bool, data: Any = None, error: Optional[str] = None):
        self.success = success
        self.data = data
        self.error = error


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
            return result
        except Exception as e:
            logger.error(f"[{task_name}] Failed {job_id}: {e}")
            raise

    return wrapper
