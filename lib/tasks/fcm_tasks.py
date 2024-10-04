import asyncio
import logging
from typing import List

import nest_asyncio
from celery import shared_task

from lib.schemas.fcm_notification_info import FCMNotificationInfo


@shared_task
def send_fcm_notification_task(
    user_ids: List[str], notification_info: FCMNotificationInfo
):

    from lib.services.fcm_service import FCMService

    fcm_service = FCMService()

    try:
        for user_id in user_ids:
            nest_asyncio.apply()
            asyncio.run(
                fcm_service.send_fcm_notification_to_user_devices(
                    user_id=user_id, notification_info=notification_info
                ),
            )

        print(f"==> Completed asyncio.run for user_id: {user_id}")
    except Exception as e:
        print(
            f"Failed to send FCM notification for user {user_id}. Error: {str(e)}"
        )
