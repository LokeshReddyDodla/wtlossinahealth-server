from datetime import datetime, timedelta
from uuid import UUID
from typing import Sequence
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession
from lib.models.user_device import UserDevice


async def log_last_active_time(
    request: Request,
    session: AsyncSession,
    device_list: Sequence[UserDevice],
    threshold_minutes: int = 5,
):
    device_id_str = request.headers.get("x-device-id")
    if not device_id_str:
        return

    try:
        device_id = UUID(device_id_str)
    except ValueError:
        return

    matching_device: UserDevice | None = next(
        (d for d in device_list if str(d.device_id) == str(device_id)),
        None,
    )
    if not matching_device:
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
