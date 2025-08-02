from datetime import datetime, timedelta
from uuid import UUID
from typing import Sequence
from fastapi import Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from lib.models.user_device import UserDevice
from lib.utils.http_exceptions import raise_http_exception


async def log_last_active_time(
    request: Request,
    session: AsyncSession,
    device_list: Sequence[UserDevice],
    threshold_minutes: int = 5,
):
    device_id_str = request.headers.get("x-device-id")
    if not device_id_str:
        # raise_http_exception(
        #     status_code=status.HTTP_401_UNAUTHORIZED,
        #     message="Missing x-device-id header",
        # )
        return

    try:
        device_id = UUID(device_id_str)
    except ValueError:
        # raise_http_exception(
        #     status_code=status.HTTP_401_UNAUTHORIZED,
        #     message="Invalid x-device-id format",
        # )
        return

    matching_device: UserDevice | None = next(
        (d for d in device_list if str(d.device_id) == str(device_id)),
        None,
    )
    if not matching_device:
        # raise_http_exception(
        #     status_code=status.HTTP_401_UNAUTHORIZED,
        #     message="Device not registered. Please log in again.",
        # )
        return

    last_active_at_value = matching_device.last_active_at
    now = datetime.now()

    if last_active_at_value is None or (
        now - last_active_at_value
    ) > timedelta(
        minutes=threshold_minutes
    ):  # type: ignore
        matching_device.last_active_at = now  # type: ignore
        await session.commit()
