import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from decouple import config
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker

logger = logging.getLogger(__name__)

# Read PostgreSQL URL from env
SQLALCHEMY_DATABASE_URL = config("POSTGRES_ASYNCPG_URL")

# Ensure the URL is using asyncpg
if not SQLALCHEMY_DATABASE_URL.startswith("postgresql+asyncpg://"):
    raise ValueError("POSTGRES_URL must start with 'postgresql+asyncpg://'")

# Seven processes (2 API workers + 5 arq workers) share one Postgres, so the
# per-process pool must stay small; PgBouncer in front multiplexes the rest.
engine = create_async_engine(
    SQLALCHEMY_DATABASE_URL,
    pool_size=int(config("POSTGRES_POOL_SIZE", default=10)),
    max_overflow=int(config("POSTGRES_MAX_OVERFLOW", default=5)),
    pool_timeout=30,
    pool_recycle=3600,
    pool_pre_ping=True,
    echo=False,
    future=True,
    # PgBouncer transaction pooling breaks asyncpg's prepared-statement cache
    # (statements outlive the server connection they were prepared on).
    connect_args={"statement_cache_size": 0},
)

# Create a configured "Session" class
AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Create a Base class for our models to inherit
Base = declarative_base()


class PostgresStore:
    def __init__(self):
        self.engine = engine
        self.session_local = AsyncSessionLocal

    @asynccontextmanager
    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        session: AsyncSession = self.session_local()
        logger.debug(
            f"🔌 Acquiring connection (checked out: {self.engine.pool.checkedout()}, "
            f"in pool: {self.engine.pool.checkedin()})"
        )

        try:
            yield session
        except Exception as e:
            logger.error(f"Session error: {e}")
            await session.rollback()
            logger.info("↩️ Rolled back transaction")
            raise
        finally:
            await session.close()
            logger.debug(
                f"🔓 Releasing connection (checked out: {self.engine.pool.checkedout()}, "
                f"in pool: {self.engine.pool.checkedin()})"
            )

    async def close(self):
        await self.engine.dispose()
        logger.info("🛑 Database connection closed")
