from typing import AsyncGenerator

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from lib.core.postgres_store import PostgresStore

postgres_store = PostgresStore()


async def get_postgres_session() -> AsyncGenerator[AsyncSession, None]:
    async for session in postgres_store.get_session():
        yield session
