import asyncpg
from clickhouse_driver.errors import Error as ClickHouseError
from fastapi import Depends, HTTPException
from pymongo.errors import PyMongoError
from redis import RedisError
from sqlalchemy.sql import text

from lib.dependencies.database import get_postgres_session


async def check_postgres_health(request, session):
    try:
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


async def check_clickhouse_health(request):
    try:
        result = request.state.context.clickhouse_store.client.execute(
            "SELECT 1"
        )
        if result:
            return "available"
    except ClickHouseError:
        raise HTTPException(status_code=503, detail="ClickHouse unavailable")
