from contextlib import asynccontextmanager
from typing import AsyncGenerator

from decouple import config
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Read PostgreSQL URL from env
SQLALCHEMY_DATABASE_URL = config("POSTGRES_ASYNCPG_URL")

# Ensure the URL is using asyncpg
if not SQLALCHEMY_DATABASE_URL.startswith("postgresql+asyncpg://"):
    raise ValueError("POSTGRES_URL must start with 'postgresql+asyncpg://'")

# Create the SQLAlchemy engine
engine = create_async_engine(
    SQLALCHEMY_DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
    pool_recycle=1800,
    pool_pre_ping=True,
    echo=False,
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
        try:
            yield session
        finally:
            await session.close()

    async def __aenter__(self):
        self.session = self.session_local()
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        await self.session.close()
