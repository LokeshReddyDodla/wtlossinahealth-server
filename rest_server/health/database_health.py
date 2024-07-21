import asyncpg
from redis import RedisError
from pymongo.errors import PyMongoError
from fastapi import HTTPException
from sqlalchemy.sql import text


async def check_postgres_health(request):
    try:
        async with request.state.context.postgres_store.get_session() as session:
            await session.execute(text("SELECT 1"))
        return "available"
    except asyncpg.PostgresError:
        raise HTTPException(status_code=503, detail="Postgres unavailable")


async def check_redis_health(request):
    try:
        if request.state.context.otp_store.is_connected():
            return "available"
    except RedisError:
        raise HTTPException(status_code=503, detail="Redis unavailable")


async def check_mongodb_health(request):
    try:
        if request.state.context.mongo_store.client.server_info():
            return "available"
    except PyMongoError:
        raise HTTPException(status_code=503, detail="MongoDB unavailable")
