import logging
from functools import wraps
import time
from typing import Any, Callable, Coroutine
import uuid
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


def with_postgres_session(func: Callable[..., Coroutine[Any, Any, Any]]):
    """Decorator to automatically manage sessions for service methods."""

    @wraps(func)
    async def wrapper(self, *args, **kwargs):
        if not hasattr(self, "postgres_store"):
            raise AttributeError(
                "Service must have a 'postgres_store' attribute."
            )

        # If session is already passed, reuse it
        if (
            "postgres_session" in kwargs
            and kwargs["postgres_session"] is not None
        ):
            return await func(self, *args, **kwargs)

        method_id = uuid.uuid4().hex[:8]
        logger.info(f"[{method_id}] ▶️ {func.__name__} starting...")

        if hasattr(self.postgres_store.engine, "pool"):
            pool = self.postgres_store.engine.pool
            logger.info(
                f"[{method_id}] Connection pool - size: {pool.size()}, "
                f"checked in: {pool.checkedin()}, "
                f"checked out: {pool.checkedout()}, "
                f"overflow: {pool.overflow()}"
            )

        start_time = time.perf_counter()
        async with self.postgres_store.get_session() as postgres_session:
            logger.info(f"Connection acquired for {func.__name__}.")
            try:
                # Inject the session into the method if it accepts a `postgres_session` parameter
                logger.info(
                    f"[{method_id}] ✅ DB session acquired for {func.__name__}"
                )
                kwargs["postgres_session"] = postgres_session
                result = await func(self, *args, **kwargs)
                elapsed = time.perf_counter() - start_time
                logger.info(
                    f"[{method_id}] ✅ {func.__name__} completed in {elapsed:.2f}s"
                )
                return result
            except SQLAlchemyError as e:
                logger.error(
                    f"[{method_id}] ❌ SQLAlchemyError in {func.__name__}: {e}"
                )
                raise
            except Exception as e:
                logger.exception(
                    f"[{method_id}] ❌ Unexpected error in {func.__name__}: {e}"
                )
                raise
            finally:
                logger.info(
                    f"[{method_id}] 🔚 Releasing DB session for {func.__name__}"
                )

    return wrapper
