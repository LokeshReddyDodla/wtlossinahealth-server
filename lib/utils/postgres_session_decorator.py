import logging
import time
from functools import wraps
from typing import Any, Callable, Coroutine

from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)

SLOW_QUERY_THRESHOLD_S = 2.0


def with_postgres_session(func: Callable[..., Coroutine[Any, Any, Any]]):
    @wraps(func)
    async def wrapper(self, *args, **kwargs):
        if not hasattr(self, "postgres_store"):
            raise AttributeError(
                "Service must have a 'postgres_store' attribute."
            )

        if (
            "postgres_session" in kwargs
            and kwargs["postgres_session"] is not None
        ):
            return await func(self, *args, **kwargs)

        start_time = time.perf_counter()
        async with self.postgres_store.get_session() as postgres_session:
            try:
                kwargs["postgres_session"] = postgres_session
                result = await func(self, *args, **kwargs)
                elapsed = time.perf_counter() - start_time
                if elapsed >= SLOW_QUERY_THRESHOLD_S:
                    logger.warning(
                        "slow_db_call method=%s duration=%.2fs", func.__name__, elapsed
                    )
                return result
            except SQLAlchemyError as e:
                logger.error("db_error method=%s error=%s", func.__name__, e)
                raise
            except Exception as e:
                logger.exception("unexpected_error method=%s error=%s", func.__name__, e)
                raise

    return wrapper
