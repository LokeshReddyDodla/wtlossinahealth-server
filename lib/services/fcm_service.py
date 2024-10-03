from typing import Optional
from uuid import UUID

import firebase_admin
import httpx
from decouple import config
from firebase_admin import credentials, messaging
from google.auth.transport.requests import Request
from google.oauth2 import service_account

from lib.core.constants import FCMProject, ProfileType
from lib.core.postgres_store import PostgresStore
from lib.services.user_device_service import UserDeviceService


class FCMService:
    def __init__(
        self,
        project: FCMProject = FCMProject.PATIENT_APP,
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
        channel_id: str = "other",
    ):
        """Send an FCM notification to a single device using firebase-admin."""
        message = self._build_message(
            fcm_token, title, body, channel_id, data=data
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
        channel_id: str,
        data: dict = {},
    ) -> messaging.Message:
        """Build a messaging.Message object."""
        notification = messaging.Notification(
            title=title,
            body=body,
        )

        # Android-specific config
        android_config = messaging.AndroidConfig(
            notification=messaging.AndroidNotification(channel_id=channel_id)
        )

        # iOS-specific config
        apns_config = messaging.APNSConfig(
            payload=messaging.APNSPayload(
                aps=messaging.Aps(sound="default", badge=1)
            )
        )

        return messaging.Message(
            token=fcm_token,
            notification=notification,
            data=data,
            android=android_config,
            apns=apns_config,
        )

    async def send_fcm_notification_to_user_devices(
        self,
        user_id: str,
        title: str,
        body: str,
        data: dict = {},
        append_name: bool = False,
        channel_id: str = "other",
    ):
        """Send a batch of FCM notifications to all devices of a user."""
        print("==> sending fcm notification to user devices...")
        
        try:
            async for session in PostgresStore().get_session():
                user_device_service = UserDeviceService(
                    postgres_session=session
                )
                # Fetch all devices associated with the user_id
                devices = await user_device_service.get_user_devices(
                    user_id=UUID(user_id)
                )

                # Create a list to hold all messages
                messages = []
                for device in devices:
                    notification_title = title

                    if append_name:
                        if (
                            device.profile_type == ProfileType.PATIENT.value
                            and device.patient
                        ):
                            notification_title += (
                                f" {device.patient.first_name}"
                            )
                        elif (
                            device.profile_type
                            == ProfileType.CARE_PROVIDER.value
                            and device.care_provider
                        ):
                            notification_title += (
                                f" {device.care_provider.first_name}"
                            )

                    # Build the message
                    message = self._build_message(
                        fcm_token=device.fcm_token,
                        title=notification_title,
                        body=body,
                        channel_id=channel_id,
                        data=data,
                    )
                    messages.append(message)

                # Send all messages in a batch
                response = messaging.send_each(messages)
                print(f"Batch notification response: {response}")
        except Exception as e:
            print(f"Failed to send batch notifications. Error: {str(e)}")
