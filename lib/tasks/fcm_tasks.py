from celery import shared_task


@shared_task(queue="default")
async def send_fcm_notification_task(participants, notification_info: dict):

    from lib.services.fcm_service import FCMService

    fcm_service = FCMService()

    try:
        for participant in participants:
            user_id = str(participant["id"])
            is_muted = participant["is_muted"]

            if not is_muted:
                await fcm_service.send_fcm_notification_to_user_devices(
                    user_id=user_id,
                    title=notification_info["title"],
                    body=notification_info["body"],
                    channel_key=notification_info["channel_key"],
                    group_key=notification_info["group_key"],
                    data=notification_info["data"],
                )

        print(f"✅ Notification sent to user_id: {user_id}")
    except Exception as e:
        print(
            f"Failed to send FCM notification for user {user_id}. Error: {str(e)}"
        )
