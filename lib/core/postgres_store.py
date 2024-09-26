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
engine = create_async_engine(SQLALCHEMY_DATABASE_URL, echo=True)

# Create a configured "Session" class
AsyncSessionLocal = sessionmaker(
    bind=engine, class_=AsyncSession, expire_on_commit=False, 
)

# Create a Base class for our models to inherit
Base = declarative_base()


class PostgresStore:
    def __init__(self):
        self.engine = engine
        self.session_local = AsyncSessionLocal

    def get_session(self) -> AsyncSession:
        # Create an instance of AsyncSession
        async_session = self.session_local()
        try:
            yield async_session
        finally:
            await async_session.close()

    async def __aenter__(self):
        self.session = self.session_local()
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        await self.session.close()
