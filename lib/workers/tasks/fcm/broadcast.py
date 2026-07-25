"""Broadcast FCM notification to all patients with active devices."""

from typing import Any, Dict, List, Literal, Optional

from firebase_admin import messaging
from loguru import logger
from sqlalchemy import func, select

from lib.core.postgres_store import PostgresStore
from lib.core.types import (
    FCMNotificationChannelKeyLiteral,
    FCMNotificationGroupKeyLiteral,
)
from lib.models.user_device import UserDevice
from lib.utils.json_utils import ensure_string_values
from lib.workers.arq.config import Queues
from lib.workers.arq.redis import enqueue_job
from lib.workers.tasks.base import TaskResult, task_with_logging

# Firebase multicast limit is 500 tokens per call
FCM_MULTICAST_LIMIT = 500


@task_with_logging
async def process_broadcast_notification(
    ctx: Dict[str, Any],
    notification_info: Dict[str, Any],
) -> TaskResult:
    """Bulk-query all patient FCM tokens and send via multicast directly.

    Skips per-user permission checks and device lookups — this is an
    admin-initiated broadcast, so we send to everyone with a token.
    """
    try:
        store = PostgresStore()
        try:
            async with store.get_session() as session:
                q = select(UserDevice.fcm_token).where(
                    UserDevice.fcm_token.isnot(None),
                    UserDevice.is_active.is_(True),
                    UserDevice.profile_type == "patient",
                )
                platform = notification_info.get("platform", "all")
                if platform == "android":
                    q = q.where(func.lower(UserDevice.device_type) == "android")
                elif platform == "ios":
                    q = q.where(func.lower(UserDevice.device_type).in_(["ios", "iphone", "ipad"]))

                result = await session.execute(q)
                tokens = [row[0] for row in result.all()]
        finally:
            await store.close()

        if not tokens:
            logger.warning("No FCM tokens found for broadcast")
            return TaskResult(
                success=True,
                data={"total_tokens": 0, "sent": 0, "failed": 0},
            )

        title = notification_info["title"]
        body = notification_info["body"]
        channel_key = notification_info.get("channel_key", "other")
        group_key = notification_info.get("group_key", "other_group")
        data = ensure_string_values(
            {
                **(notification_info.get("data") or {}),
                "groupKey": group_key,
                "channelKey": channel_key,
            }
        )

        total_success = 0
        total_failure = 0

        for i in range(0, len(tokens), FCM_MULTICAST_LIMIT):
            batch = tokens[i : i + FCM_MULTICAST_LIMIT]
            multicast = messaging.MulticastMessage(
                tokens=batch,
                notification=messaging.Notification(title=title, body=body),
                android=messaging.AndroidConfig(
                    notification=messaging.AndroidNotification(
                        channel_id=channel_key
                    )
                ),
                apns=messaging.APNSConfig(
                    payload=messaging.APNSPayload(
                        aps=messaging.Aps(sound="default"),
                        mutable_content=True,
                    )
                ),
                data=data,
            )

            response = messaging.send_each_for_multicast(multicast)
            total_success += response.success_count
            total_failure += response.failure_count

            if response.failure_count:
                for idx, resp in enumerate(response.responses):
                    if not resp.success:
                        logger.warning(
                            f"Broadcast FCM fail token {batch[idx][:20]}...: "
                            f"{resp.exception}"
                        )

        logger.info(
            f"Broadcast complete: {total_success} sent, "
            f"{total_failure} failed out of {len(tokens)} tokens"
        )

        return TaskResult(
            success=True,
            data={
                "total_tokens": len(tokens),
                "sent": total_success,
                "failed": total_failure,
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
    platform: Literal["all", "android", "ios"] = "all",
    data: Optional[dict] = None,
) -> Optional[str]:
    notification_info = {
        "title": title,
        "body": body,
        "channel_key": channel_key,
        "group_key": group_key,
        "platform": platform,
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
