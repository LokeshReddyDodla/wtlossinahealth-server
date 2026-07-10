from datetime import datetime, timedelta
from uuid import UUID
from typing import Optional, Sequence
import os
from fastapi import Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from lib.core.constants import ProfileTypeEnum
from lib.models.user_activity_log import UserActivityLog
from lib.models.user_device import UserDevice
from lib.utils.http_exceptions import raise_http_exception


async def log_last_active_time(
    request: Request,
    session: AsyncSession,
    user_id: str,
    profile_type: ProfileTypeEnum,
    threshold_minutes: int = 5,
):
    # Admins don't require device verification
    if profile_type == ProfileTypeEnum.ADMIN:
        return

    if request.headers.get("x-background") == "true":
        return

    env = os.getenv("ENV", "dev").lower()
    is_production = env in ("prod", "production")

    device_id_str = request.headers.get("x-device-id")
    if not device_id_str:
        if is_production:
            raise_http_exception(
                status_code=status.HTTP_401_UNAUTHORIZED,
                message="Missing x-device-id header",
            )
        return

    # Validate device ID format
    try:
        device_id = UUID(device_id_str)
    except ValueError:
        raise_http_exception(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message="Invalid x-device-id format",
        )

    # Fetch user's registered devices
    result = await session.execute(
        select(UserDevice).where(
            UserDevice.user_id == user_id,
            UserDevice.profile_type == profile_type.value,
        )
    )
    devices = result.scalars().all()

    # If user has no devices but sent a device ID, reject the request
    if not devices:
        raise_http_exception(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message="Device not registered. Please log in again.",
        )

    # Verify the device ID matches one of the user's registered devices
    matching_device: Optional[UserDevice] = next(
        (d for d in devices if str(d.device_id) == str(device_id)),
        None,
    )
    if not matching_device:
        raise_http_exception(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message="Device not registered. Please log in again.",
        )

    now = datetime.now()

    if matching_device.last_active_at is None or (
        now - matching_device.last_active_at
    ) > timedelta(minutes=threshold_minutes):  # type: ignore
        matching_device.last_active_at = now  # type: ignore

    session.add(
        UserActivityLog(
            user_id=matching_device.user_id,
            profile_type=profile_type.value,
            device_id=matching_device.device_id,
            api_endpoint=request.url.path,
            method=request.method,
            ip_address=request.client.host if request.client else None,
            status_code=None,  # TODO: populate this in middleware after response
            active_at=now,
        )
    )

    await session.commit()
