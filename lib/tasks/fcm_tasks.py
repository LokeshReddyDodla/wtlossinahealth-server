import asyncio
import logging

import nest_asyncio
from celery import shared_task


@shared_task
def send_fcm_notification_task(
    user_id, title, body, data=None, append_name=False, channel_id="other"
):

    from lib.services.fcm_service import FCMService

    fcm_service = FCMService()

    try:
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

        print(f"==> Completed asyncio.run for user_id: {user_id}")
    except Exception as e:
        print(
            f"Failed to send FCM notification for user {user_id}. Error: {str(e)}"
        )
