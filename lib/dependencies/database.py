from typing import AsyncGenerator

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from lib.core.postgres_store import PostgresStore


async def get_postgres_session() -> AsyncGenerator[AsyncSession, None]:
    session: AsyncSession = PostgresStore().get_session()
    try:
        yield session
    finally:
        await session.close()