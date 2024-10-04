import asyncio
import logging
from typing import List

import nest_asyncio
from celery import shared_task

from lib.schemas.fcm_notification_info import FCMNotificationInfo


@shared_task
def send_fcm_notification_task(participants, notification_info: dict):

    from lib.services.fcm_service import FCMService

    fcm_service = FCMService()

    try:
        for participant in participants:
            user_id = str(participant["id"])
            is_muted = participant["is_muted"]

            if not is_muted:
                nest_asyncio.apply()
                asyncio.run(
                    fcm_service.send_fcm_notification_to_user_devices(
                        user_id=user_id,
                        title=notification_info["title"],
                        body=notification_info["body"],
                        channel_id=notification_info["channel_id"],
                        append_name=notification_info["append_name"],
                        data=notification_info["data"],
                    ),
                )

        print(f"==> Completed asyncio.run for user_id: {user_id}")
    except Exception as e:
        print(
            f"Failed to send FCM notification for user {user_id}. Error: {str(e)}"
        )
