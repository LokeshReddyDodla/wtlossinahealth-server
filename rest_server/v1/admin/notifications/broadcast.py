from typing import Literal, Optional

from fastapi import Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from lib.core.postgres_store import PostgresStore
from lib.dependencies.auth.admin_auth import get_current_admin
from lib.models.admin import Admin
from lib.models.user_device import UserDevice
from lib.workers.tasks.fcm.broadcast import enqueue_broadcast_notification
from lib.core.types import (
    FCMNotificationChannelKeyLiteral,
    FCMNotificationGroupKeyLiteral,
)
from rest_server.response_models import SuccessResponse
from lib.utils.http_exceptions import raise_http_exception

from .router import router

PlatformFilter = Literal["all", "android", "ios"]


class BroadcastNotificationRequest(BaseModel):
    title: str = Field(max_length=200)
    body: str = Field(max_length=1000)
    channel_key: FCMNotificationChannelKeyLiteral = "other"
    group_key: FCMNotificationGroupKeyLiteral = "other_group"
    platform: PlatformFilter = "all"
    data: Optional[dict] = None


@router.post(
    "/broadcast",
    response_model=SuccessResponse,
)
async def broadcast_notification(
    body: BroadcastNotificationRequest,
    current_admin: Admin = Depends(get_current_admin),
):
    try:
        job_id = await enqueue_broadcast_notification(
            title=body.title,
            body=body.body,
            channel_key=body.channel_key,
            group_key=body.group_key,
            platform=body.platform,
            data=body.data or {},
        )

        return SuccessResponse(
            message="Broadcast notification enqueued.",
            data={"job_id": job_id},
        )
    except HTTPException:
        raise
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to enqueue broadcast notification.",
            detail=str(e),
        )


@router.get("/broadcast/device-count", response_model=SuccessResponse)
async def get_broadcast_device_count(
    platform: PlatformFilter = Query("all"),
    current_admin: Admin = Depends(get_current_admin),
):
    store = PostgresStore()
    try:
        async with store.get_session() as session:
            q = select(func.count()).where(
                UserDevice.fcm_token.isnot(None),
                UserDevice.is_active.is_(True),
                UserDevice.profile_type == "patient",
            )
            if platform == "android":
                q = q.where(func.lower(UserDevice.device_type) == "android")
            elif platform == "ios":
                q = q.where(func.lower(UserDevice.device_type).in_(["ios", "iphone", "ipad"]))

            result = await session.execute(q)
            count = result.scalar() or 0
    finally:
        await store.close()

    return SuccessResponse(
        message="Device count",
        data={"count": count, "platform": platform},
    )
