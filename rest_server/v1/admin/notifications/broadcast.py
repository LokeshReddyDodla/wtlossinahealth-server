from typing import Optional

from fastapi import Depends, HTTPException, status
from pydantic import BaseModel, Field

from lib.dependencies.auth.admin_auth import get_current_admin
from lib.models.admin import Admin
from lib.workers.tasks.fcm.broadcast import enqueue_broadcast_notification
from lib.core.types import (
    FCMNotificationChannelKeyLiteral,
    FCMNotificationGroupKeyLiteral,
)
from rest_server.response_models import SuccessResponse
from lib.utils.http_exceptions import raise_http_exception

from .router import router


class BroadcastNotificationRequest(BaseModel):
    title: str = Field(max_length=200)
    body: str = Field(max_length=1000)
    channel_key: FCMNotificationChannelKeyLiteral = "other"
    group_key: FCMNotificationGroupKeyLiteral = "other_group"
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
