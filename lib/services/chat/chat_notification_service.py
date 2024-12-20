from typing import List, Optional

from lib.schemas.fcm_notification_info import FCMNotificationInfo
from lib.services.chat.base import BaseChatService
from lib.services.chat.chat_participant_service import ChatParticipantService
from lib.tasks.fcm_tasks import send_fcm_notification_task


class ChatNotificationService(BaseChatService):
    def __init__(self):
        self.participant_service = ChatParticipantService()

    async def notify_participants(
        self,
        message_key: str,
        data: Optional[dict] = None,
        chat_id: Optional[str] = None,
        user_id: Optional[str] = None,
        notification_info: Optional[FCMNotificationInfo] = None,
    ):

        from lib.services.socketio_service import sio

        try:
            # Fetch participants for the chat
            participants = (
                await self.participant_service.fetch_chat_participants(
                    chat_id, user_id
                )
            )

            # Emit WebSocket message to participants
            for participant in participants:
                participant_id = str(participant["id"])
                await sio.emit(message_key, data, room=participant_id)
                print(f"Emitted {message_key} to participant {participant_id}")

            # Send FCM notification if required
            if notification_info:
                self._send_fcm_notifications(participants, notification_info)

        except Exception as e:
            print(f"Failed to emit {message_key} to participants: {str(e)}")
            raise Exception(f"Failed to notify participants: {str(e)}")

    def _send_fcm_notifications(
        self, participants: List[dict], notification_info: FCMNotificationInfo
    ):
        try:
            # Filter participants to exclude the sender
            filtered_participants = self._filter_participants_for_fcm(
                participants, notification_info.sender_id  # type: ignore
            )

            # Trigger FCM notification task
            send_fcm_notification_task.delay(
                participants=filtered_participants,
                notification_info=notification_info.dict(),
            )
            print(
                f"FCM notifications sent to {len(filtered_participants)} participants."
            )
        except Exception as e:
            print(f"Failed to send FCM notifications: {str(e)}")
            raise Exception(f"Failed to send FCM notifications: {str(e)}")

    def _filter_participants_for_fcm(
        self, participants: List[dict], sender_id: str
    ) -> List[dict]:
        return [p for p in participants if str(p["id"]) != sender_id]

    def _get_notification_body(self, message_type: str, content: str) -> str:
        if message_type == "image":
            return "You received an image"
        elif message_type == "file":
            return "You received a file"
        elif message_type == "audio":
            return "You received an audio message"
        return content
