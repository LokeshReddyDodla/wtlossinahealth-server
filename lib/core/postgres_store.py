import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from decouple import config
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Read PostgreSQL URL from env
SQLALCHEMY_DATABASE_URL = config("POSTGRES_ASYNCPG_URL")

# Ensure the URL is using asyncpg
if not SQLALCHEMY_DATABASE_URL.startswith("postgresql+asyncpg://"):
    raise ValueError("POSTGRES_URL must start with 'postgresql+asyncpg://'")

# Create the SQLAlchemy engine
engine = create_async_engine(
    SQLALCHEMY_DATABASE_URL,
    pool_size=100,
    max_overflow=10,
    pool_timeout=30,
    pool_recycle=3600,
    pool_pre_ping=True,
    echo=False,
    future=True,
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
        logger.info(
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
            logger.info(
                f"🔓 Releasing connection (checked out: {self.engine.pool.checkedout()}, "
                f"in pool: {self.engine.pool.checkedin()})"
            )

    async def close(self):
        await self.engine.dispose()
        logger.info("🛑 Database connection closed")
