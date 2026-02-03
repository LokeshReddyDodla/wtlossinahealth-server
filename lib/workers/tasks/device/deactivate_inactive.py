"""Device deactivation tasks."""

from datetime import datetime, timedelta
from typing import Any, Dict

from loguru import logger
from sqlalchemy import desc, update
from sqlalchemy.future import select

from lib.dependencies.database import get_async_postgres_session
from lib.models.user_device import UserDevice
from lib.workers.tasks.base import TaskResult, task_with_logging


@task_with_logging
async def deactivate_inactive_devices(
    ctx: Dict[str, Any],
) -> TaskResult:
    """
    Weekly job to deactivate devices that have been inactive for more than 30 days.
    Keeps the 3 most recent devices active for each user, regardless of inactivity status.
    Marks all other inactive devices (more than 30 days) as is_active = False.
    """
    try:
        cutoff_date = datetime.now().replace(tzinfo=None) - timedelta(days=30)

        async with get_async_postgres_session() as session:
            user_ids_stmt = (
                select(UserDevice.user_id)
                .where(UserDevice.is_active.is_(True))
                .distinct()
            )
            result = await session.execute(user_ids_stmt)
            user_ids = [row[0] for row in result.all()]

            if not user_ids:
                logger.info("No users with active devices found")
                return TaskResult(
                    success=True,
                    data={
                        "users_processed": 0,
                        "devices_deactivated": 0,
                    },
                )

            total_deactivated = 0
            users_processed = 0

            for user_id in user_ids:
                deactivated_count = await _deactivate_user_inactive_devices(
                    session, user_id, cutoff_date
                )
                if deactivated_count > 0:
                    total_deactivated += deactivated_count
                    users_processed += 1

            await session.commit()

            logger.info(
                f"✅ Deactivated {total_deactivated} inactive devices "
                f"for {users_processed} users (keeping 3 most recent active per user)"
            )

            return TaskResult(
                success=True,
                data={
                    "users_processed": users_processed,
                    "devices_deactivated": total_deactivated,
                    "total_users_checked": len(user_ids),
                },
            )

    except Exception as e:
        logger.error(f"❌ Failed to deactivate inactive devices: {e}")
        return TaskResult(
            success=False,
            error=str(e),
            data={},
        )


async def _deactivate_user_inactive_devices(
    session,
    user_id: str,
    cutoff_date: datetime,
) -> int:
    """
    Deactivate inactive devices for a single user.
    Keeps the 3 most recent devices active.
    """
    devices_stmt = (
        select(UserDevice)
        .where(
            UserDevice.user_id == user_id,
            UserDevice.is_active.is_(True),
        )
        .order_by(
            desc(UserDevice.last_active_at).nullslast(),
            desc(UserDevice.created_at),
        )
    )

    result = await session.execute(devices_stmt)
    devices = list(result.scalars().all())

    if not devices:
        return 0

    inactive_devices = [
        device
        for device in devices
        if device.last_active_at is None or device.last_active_at < cutoff_date
    ]

    if not inactive_devices:
        return 0

    most_recent_device_ids = {device.device_id for device in devices[:3]}

    devices_to_deactivate = [
        device.device_id
        for device in inactive_devices
        if device.device_id not in most_recent_device_ids
    ]

    if not devices_to_deactivate:
        return 0

    update_stmt = (
        update(UserDevice)
        .where(UserDevice.device_id.in_(devices_to_deactivate))
        .values(
            is_active=False,
            last_updated_at=datetime.now().replace(tzinfo=None),
        )
    )

    await session.execute(update_stmt)

    logger.debug(f"Deactivated {len(devices_to_deactivate)} devices for user {user_id}")

    return len(devices_to_deactivate)
