from fastapi import APIRouter, Request
from rest_server.health.database_health import (
    check_postgres_health,
    check_redis_health,
    check_mongodb_health,
)
from rest_server.health.api_health import check_user_api_health
from rest_server.response_models import SuccessResponse

router = APIRouter(prefix="/health")


@router.get("/health/postgres", tags=["Health"])
async def postgres_health_check(request: Request):
    await check_postgres_health(request)
    return SuccessResponse(message="Postgres is available")


@router.get("/health/redis", tags=["Health"])
async def redis_health_check(request: Request):
    await check_redis_health(request)
    return SuccessResponse(message="Redis is available")


@router.get("/health/mongodb", tags=["Health"])
async def mongodb_health_check(request: Request):
    await check_mongodb_health(request)
    return SuccessResponse(message="MongoDB is available")


@router.get("/health/user-api", tags=["Health"])
async def user_api_health_check():
    await check_user_api_health()
    return SuccessResponse(message="User API is available")
