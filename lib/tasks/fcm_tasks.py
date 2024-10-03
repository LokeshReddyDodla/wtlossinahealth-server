import asyncio
import logging

import nest_asyncio
from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task
def send_fcm_notification_task(
    user_id, title, body, data=None, append_name=False, channel_id="other"
):
    logger.info(
        f"==> Entered send_fcm_notification_task for user_id: {user_id}"
    )

    from lib.services.fcm_service import FCMService

    logger.info(f"==> Imported FCMService successfully")

    fcm_service = FCMService()
    logger.info(f"==> Created FCMService instance")

    try:
        logger.info(f"==> Calling asyncio.run for user_id: {user_id}")
        nest_asyncio.apply()
        asyncio.run(
            fcm_service.send_fcm_notification_to_user_devices(
                user_id=user_id,
                title=title,
                body=body,
                data=data if data else {},
                append_name=append_name,
                channel_id=channel_id,
            ),
            debug=True,
        )

        logger.info(f"==> Completed asyncio.run for user_id: {user_id}")
    except Exception as e:
        logger.info(
            f"Failed to send FCM notification for user {user_id}. Error: {str(e)}"
        )
