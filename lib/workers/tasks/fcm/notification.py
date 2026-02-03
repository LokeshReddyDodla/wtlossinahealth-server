"""FCM Notification Tasks."""

from typing import Any, Dict, List, Optional

from loguru import logger

from lib.workers.arq.config import Queues
from lib.workers.arq.redis import enqueue_job
from lib.workers.tasks.base import TaskResult, task_with_logging


@task_with_logging
async def process_fcm_notification(
    ctx: Dict[str, Any],
    participants: List[Dict],
    notification_info: Dict[str, Any],
) -> TaskResult:
    """Send FCM notifications to a list of participants."""
    from lib.dependencies.service_dependencies import get_fcm_service

    try:
        fcm_service = get_fcm_service()
        sent_count = 0
        failed_count = 0

        for participant in participants:
            user_id = str(participant["id"])
            # NOTE: is_muted is a special case used for chat notifications only.
            # For other notification types (e.g., meal reminders), this check should not be used
            # as notification permissions are handled at the FCM service level.
            is_muted = participant.get("is_muted", False)

            if is_muted:
                logger.debug(f"Skipping muted user {user_id}")
                continue

            try:
                await fcm_service.send_fcm_notification_to_user_devices(
                    user_id=user_id,
                    title=notification_info["title"],
                    body=notification_info["body"],
                    channel_key=notification_info.get("channel_key", "other"),
                    group_key=notification_info.get("group_key", "other_group"),
                    data=notification_info.get("data", {}),
                )
                sent_count += 1
                logger.info(f"Sent FCM notification to user {user_id}")
            except Exception as e:
                failed_count += 1
                logger.error(f"Failed to send FCM notification to user {user_id}: {e}")

        return TaskResult(
            success=True,
            data={
                "total_participants": len(participants),
                "sent": sent_count,
                "failed": failed_count,
            },
        )

    except Exception as e:
        logger.error(f"FCM notification task failed: {e}")
        return TaskResult(
            success=False,
            error=str(e),
            data={"total_participants": len(participants), "sent": 0, "failed": 0},
        )


async def _enqueue_fcm_notification(
    participants: List[Dict], notification_info: Dict[str, Any]
) -> Optional[str]:
    """Internal: Enqueue FCM notification task."""
    if not participants:
        logger.warning("No participants provided for FCM notification")
        return None

    job = await enqueue_job(
        "process_fcm_notification",
        participants,
        notification_info,
        _queue_name=Queues.DEFAULT,
    )

    if job:
        logger.info(f"Enqueued FCM notification for {len(participants)} participants")

    return job.job_id if job else None
