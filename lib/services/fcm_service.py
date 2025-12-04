from typing import Optional, cast
from uuid import UUID

import firebase_admin
from decouple import config
from fastapi.encoders import jsonable_encoder
from firebase_admin import credentials, messaging
from google.oauth2 import service_account

from lib.core.constants import FCMProjectEnum
from lib.core.postgres_store import PostgresStore
from lib.core.types import (
    FCMNotificationChannelKeyLiteral,
    FCMNotificationGroupKeyLiteral,
)
from lib.services.user_device_service import UserDeviceService
from lib.utils.json_utils import ensure_string_values
from lib.core.container import container


class FCMService:
    def __init__(
        self,
        project: FCMProjectEnum = FCMProjectEnum.PATIENT_APP,
    ):
        self.json_key_path = config("FCM_JSON_KEY_PATH")
        self.project_id = project.value
        self._initialize_firebase()

    def _load_credentials(self, json_key_path: str):
        """Load Google service account credentials from JSON key."""
        credentials = service_account.Credentials.from_service_account_file(
            json_key_path,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        return credentials

    def _initialize_firebase(self):
        """Initialize the Firebase app using the service account JSON key."""
        if not firebase_admin._apps:
            cred = credentials.Certificate(self.json_key_path)
            firebase_admin.initialize_app(cred)

    async def send_fcm_notification(
        self,
        fcm_token: str,
        title: str,
        body: str,
        data: dict = {},
        channel_key: FCMNotificationChannelKeyLiteral = "other",
        group_key: FCMNotificationGroupKeyLiteral = "other_group",
    ):
        """Send an FCM notification to a single device using firebase-admin."""
        message = self._build_message(
            fcm_token, title, body, channel_key, group_key, data=data
        )
        try:
            response = messaging.send(message)
            print(f"Notification sent to {fcm_token}. Response: {response}")
        except Exception as e:
            print(
                f"Failed to send notification to {fcm_token}. Error: {str(e)}"
            )

    def _build_message(
        self,
        fcm_token: str,
        title: str,
        body: str,
        channel_key: FCMNotificationChannelKeyLiteral,
        group_key: FCMNotificationGroupKeyLiteral,
        data: dict = {},
    ) -> messaging.Message:
        """Build a messaging.Message object."""
        notification = messaging.Notification(
            title=title,
            body=body,
        )

        # Android-specific config
        android_config = messaging.AndroidConfig(
            notification=messaging.AndroidNotification(channel_id=channel_key)
        )

        # iOS-specific config
        apns_config = messaging.APNSConfig(
            payload=messaging.APNSPayload(
                aps=messaging.Aps(sound="default"), mutable_content=True
            )
        )

        data.update(
            {
                "groupKey": group_key,
                "channelKey": channel_key,
            }
        )

        return messaging.Message(
            token=fcm_token,
            notification=notification,
            data=ensure_string_values(data),
            android=android_config,
            apns=apns_config,
        )

    async def send_fcm_notification_to_user_devices(
        self,
        user_id: str,
        title: str,
        body: str,
        channel_key: FCMNotificationChannelKeyLiteral,
        group_key: FCMNotificationGroupKeyLiteral,
        data: Optional[dict] = {},
    ):
        """Send a batch of FCM notifications to all devices of a user."""

        try:
            user_device_service = UserDeviceService(
                postgres_store=cast(
                    PostgresStore, container.resolve(PostgresStore)
                )
            )

            # Fetch all devices associated with the user_id
            devices = await user_device_service.get_user_devices(
                user_id=UUID(user_id)
            )  # type: ignore
            print(f"==> user_id -> {user_id} -> devices: {devices}")

            # Collect valid tokens
            tokens = [
                d.fcm_token for d in devices if getattr(d, "fcm_token", None)
            ]
            if not tokens:
                print(f"⚠️ No valid fcm_token found for user {user_id}")
                return

            # Build multicast message
            multicast_message = messaging.MulticastMessage(
                tokens=tokens,
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
                data=ensure_string_values(
                    {
                        **(jsonable_encoder(data) or {}),
                        "groupKey": group_key,
                        "channelKey": channel_key,
                    }
                ),
            )

            # Send notifications
            response = messaging.send_each_for_multicast(multicast_message)

            # Handle individual responses
            for idx, resp in enumerate(response.responses):
                token = tokens[idx]
                if not resp.success:
                    print(
                        f"❌ Failed to send to {token}. Error: {resp.exception}"
                    )
                else:
                    print(f"✅ Successfully sent to {token}")

            print(
                f"📦 Batch notification summary: {response.success_count} success, {response.failure_count} failure(s)"
            )
        except Exception as e:
            print(f"Failed to send batch notifications. Error: {str(e)}")
