"""Broadcast FCM notification to all patients with active devices."""

from typing import Any, Dict, Optional

from loguru import logger
from sqlalchemy import distinct, select

from lib.core.postgres_store import PostgresStore
from lib.core.types import (
    FCMNotificationChannelKeyLiteral,
    FCMNotificationGroupKeyLiteral,
)
from lib.models.user_device import UserDevice
from lib.workers.arq.config import Queues
from lib.workers.arq.redis import enqueue_job
from lib.workers.tasks.base import TaskResult, task_with_logging

BATCH_SIZE = 200


@task_with_logging
async def process_broadcast_notification(
    ctx: Dict[str, Any],
    notification_info: Dict[str, Any],
) -> TaskResult:
    """Query all patients with FCM tokens and send notification in batches."""
    from lib.workers.tasks.fcm.notification import _enqueue_fcm_notification

    try:
        store = PostgresStore()
        try:
            async with store.get_session() as session:
                result = await session.execute(
                    select(distinct(UserDevice.user_id)).where(
                        UserDevice.fcm_token.isnot(None),
                        UserDevice.is_active.is_(True),
                        UserDevice.profile_type == "patient",
                    )
                )
                user_ids = [str(uid) for uid in result.scalars().all()]
        finally:
            await store.close()

        if not user_ids:
            logger.warning("No patients with active FCM tokens found")
            return TaskResult(
                success=True,
                data={"total_patients": 0, "batches_enqueued": 0},
            )

        batches_enqueued = 0
        for i in range(0, len(user_ids), BATCH_SIZE):
            batch = user_ids[i : i + BATCH_SIZE]
            participants = [{"id": uid} for uid in batch]
            await _enqueue_fcm_notification(participants, notification_info)
            batches_enqueued += 1

        logger.info(
            f"Broadcast: enqueued {batches_enqueued} batches "
            f"for {len(user_ids)} patients"
        )

        return TaskResult(
            success=True,
            data={
                "total_patients": len(user_ids),
                "batches_enqueued": batches_enqueued,
            },
        )

    except Exception as e:
        logger.error(f"Broadcast notification failed: {e}")
        return TaskResult(success=False, error=str(e))


async def enqueue_broadcast_notification(
    title: str,
    body: str,
    channel_key: FCMNotificationChannelKeyLiteral = "other",
    group_key: FCMNotificationGroupKeyLiteral = "other_group",
    data: Optional[dict] = None,
) -> Optional[str]:
    notification_info = {
        "title": title,
        "body": body,
        "channel_key": channel_key,
        "group_key": group_key,
        "data": data or {},
    }

    job = await enqueue_job(
        "process_broadcast_notification",
        notification_info,
        _queue_name=Queues.DEFAULT,
    )

    if job:
        logger.info("Enqueued broadcast notification job")

    return job.job_id if job else None
