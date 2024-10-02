from uuid import UUID

import httpx
from decouple import config
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
        self.credentials = self._load_credentials(str(self.json_key_path))
        self.fcm_url = project.get_fcm_api_url()

    def _load_credentials(self, json_key_path: str):
        """Load Google service account credentials from JSON key."""
        credentials = service_account.Credentials.from_service_account_file(
            json_key_path,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        return credentials

    def _get_access_token(self) -> str:
        """Get an access token from the credentials."""
        request = Request()
        self.credentials.refresh(request)
        return self.credentials.token

    async def send_fcm_notification(
        self, fcm_token: str, title: str, body: str, data: dict = {}
    ):
        access_token = self._get_access_token()
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        payload = {
            "message": {
                "token": fcm_token,
                "notification": {
                    "title": title,
                    "body": body,
                },
                # "data": data,
            }
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.fcm_url, headers=headers, json=payload
                )
                response.raise_for_status()
                print(
                    f"Notification sent to {fcm_token}. Response: {response.json()}"
                )
        except Exception as e:
            print(
                f"Failed to send notification to {fcm_token}. Error: {str(e)}"
            )

    async def send_notification_to_user_devices(
        self,
        user_id: str,
        title: str,
        body: str,
        data: dict = {},
        append_name: bool = False,
    ):
        try:
            async for session in PostgresStore().get_session():
                user_device_service = UserDeviceService(
                    postgres_session=session
                )
                # Fetch all devices associated with the user_id
                devices = await user_device_service.get_user_devices(
                    user_id=UUID(user_id)
                )
                
                # Send notification to each device
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

                    print("==> notification_title: ", notification_title)
                    print("==> notification_body: ", body)
                    # print("==> notification_data: ", data)

                    # Send the notification using FCM
                    await self.send_fcm_notification(
                        device.fcm_token,
                        notification_title,
                        body,
                        data,
                    )
        except Exception as e:
            print(
                f"Failed to send notification to user devices. Error: {str(e)}"
            )
