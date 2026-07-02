from datetime import datetime, timezone

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import text

from lib.dependencies.auth.admin_auth import get_current_admin
from lib.dependencies.database import get_postgres_session
from lib.models.admin import Admin
from rest_server.response_models import SuccessResponse

from .router import router


@router.get("/pulse")
async def system_pulse(
    request: Request,
    session: AsyncSession = Depends(get_postgres_session),
    _admin: Admin = Depends(get_current_admin),
):
    ctx = request.state.context
    databases = {}

    try:
        await session.execute(text("SELECT 1"))
        databases["postgres"] = {"status": "up"}
    except Exception as e:
        databases["postgres"] = {"status": "down", "error": str(e)[:200]}

    try:
        databases["redis"] = {
            "status": "up" if ctx.otp_store.is_connected() else "down"
        }
    except Exception as e:
        databases["redis"] = {"status": "down", "error": str(e)[:200]}

    try:
        await ctx.mongo_store.client.server_info()
        databases["mongodb"] = {"status": "up"}
    except Exception as e:
        databases["mongodb"] = {"status": "down", "error": str(e)[:200]}

    try:
        result = ctx.clickhouse_store.client.execute("SELECT 1")
        databases["clickhouse"] = {"status": "up" if result else "down"}
    except Exception as e:
        databases["clickhouse"] = {"status": "down", "error": str(e)[:200]}

    col = ctx.mongo_store.get_collection("task_runs")
    pipeline = [
        {"$sort": {"created_at": -1}},
        {"$group": {
            "_id": "$task_name",
            "status": {"$first": "$status"},
            "duration_ms": {"$first": "$duration_ms"},
            "error": {"$first": "$error"},
            "last_run_at": {"$first": "$created_at"},
            "data": {"$first": "$data"},
        }},
        {"$sort": {"_id": 1}},
    ]
    task_runs = []
    async for doc in col.aggregate(pipeline):
        run = {
            "task_name": doc["_id"],
            "status": doc["status"],
            "duration_ms": doc.get("duration_ms"),
            "last_run_at": doc["last_run_at"].isoformat()
            if isinstance(doc["last_run_at"], datetime)
            else str(doc["last_run_at"]),
        }
        if doc.get("error"):
            run["error"] = doc["error"]
        if doc.get("data"):
            run["data"] = doc["data"]
        task_runs.append(run)

    return SuccessResponse(data={
        "databases": databases,
        "task_runs": task_runs,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    })
