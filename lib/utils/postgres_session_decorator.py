import logging
from functools import wraps
from typing import Any, Callable, Coroutine

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

        # Log the current pool size if the pool object exists
        if hasattr(self.postgres_store.engine, "pool"):
            pool = self.postgres_store.engine.pool
            logger.info(
                f"Current pool size: {pool.size()}, "
                f"checked in: {pool.checkedin()}, "
                f"checked out: {pool.checkedout()}, "
                f"overflow: {pool.overflow()}, "
            )

        logger.info(f"Acquiring database connection for {func.__name__}...")
        async with self.postgres_store.get_session() as postgres_session:
            logger.info(f"Connection acquired for {func.__name__}.")
            try:
                # Inject the session into the method if it accepts a `postgres_session` parameter
                if "postgres_session" in func.__code__.co_varnames:
                    kwargs["postgres_session"] = postgres_session
                return await func(self, *args, **kwargs)
            finally:
                logger.info(
                    f"Releasing database connection for {func.__name__}..."
                )

    return wrapper
