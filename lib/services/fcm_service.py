import asyncio
import logging
from typing import List, Optional, cast
from uuid import UUID

import firebase_admin
from decouple import config
from fastapi.encoders import jsonable_encoder
from firebase_admin import credentials, messaging
from google.oauth2 import service_account
from sqlalchemy.future import select

from lib.core.constants import FCMProjectEnum
from lib.core.container import container
from lib.core.postgres_store import PostgresStore
from lib.core.types import (
    FCMNotificationChannelKeyLiteral,
    FCMNotificationGroupKeyLiteral,
)
from lib.models.patient_permission import PatientPermission
from lib.services.user_device_service import UserDeviceService
from lib.utils.json_utils import ensure_string_values

logger = logging.getLogger(__name__)


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
            # firebase-admin is blocking network I/O — keep it off the loop.
            response = await asyncio.to_thread(messaging.send, message)
            logger.info(f"Notification sent to device. Response: {response}")
        except Exception as e:
            logger.error(f"Failed to send notification to device {fcm_token[:20]}...: {e}")
            raise

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

        android_config = messaging.AndroidConfig(
            notification=messaging.AndroidNotification(channel_id=channel_key)
        )

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

    async def _check_notification_permission(self, user_id: str) -> bool:
        """Check if user has notification permissions enabled."""
        postgres_store = cast(PostgresStore, container.resolve(PostgresStore))
        async with postgres_store.get_session() as session:
            result = await session.execute(
                select(PatientPermission).where(
                    PatientPermission.patient_id == UUID(user_id)
                )
            )
            permission = result.scalars().first()
            return permission is not None and permission.notification_permission

    def _build_multicast_message(
        self,
        tokens: List[str],
        title: str,
        body: str,
        channel_key: FCMNotificationChannelKeyLiteral,
        group_key: FCMNotificationGroupKeyLiteral,
        data: dict,
    ) -> messaging.MulticastMessage:
        """Build a multicast message for batch notification sending."""
        return messaging.MulticastMessage(
            tokens=tokens,
            notification=messaging.Notification(title=title, body=body),
            android=messaging.AndroidConfig(
                notification=messaging.AndroidNotification(channel_id=channel_key)
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

    async def send_fcm_notification_to_user_devices(
        self,
        user_id: str,
        title: str,
        body: str,
        channel_key: FCMNotificationChannelKeyLiteral,
        group_key: FCMNotificationGroupKeyLiteral,
        data: Optional[dict] = None,
        skip_permission_check: bool = False,
    ):
        """
        Send a batch of FCM notifications to all devices of a user.
        
        Args:
            user_id: The user's UUID as a string
            title: Notification title
            body: Notification body
            channel_key: FCM channel key for Android
            group_key: FCM group key for notification grouping
            data: Optional additional data payload
            skip_permission_check: If True, bypass notification permission check
        """
        if data is None:
            data = {}

        try:
            if not skip_permission_check:
                has_permission = await self._check_notification_permission(user_id)
                if not has_permission:
                    logger.info(
                        f"User {user_id} has notification permissions disabled. Skipping notification."
                    )
                    return

            postgres_store = cast(PostgresStore, container.resolve(PostgresStore))
            user_device_service = UserDeviceService(postgres_store=postgres_store)
            devices = await user_device_service.get_user_devices(
                user_id=UUID(user_id)
            )

            tokens = [
                device.fcm_token
                for device in devices
                if device.fcm_token
            ]
            
            if not tokens:
                logger.warning(f"No valid FCM tokens found for user {user_id}")
                return

            logger.info(
                f"Sending notification to user {user_id} on {len(tokens)} device(s)"
            )

            multicast_message = self._build_multicast_message(
                tokens=tokens,
                title=title,
                body=body,
                channel_key=channel_key,
                group_key=group_key,
                data=data,
            )

            # firebase-admin is blocking network I/O — keep it off the loop.
            response = await asyncio.to_thread(
                messaging.send_each_for_multicast, multicast_message
            )

            invalid_tokens: list[str] = []
            for idx, resp in enumerate(response.responses):
                if not resp.success:
                    if isinstance(resp.exception, messaging.UnregisteredError):
                        invalid_tokens.append(tokens[idx])
                    logger.warning(
                        f"Failed to send notification to device {tokens[idx][:20]}...: {resp.exception}"
                    )

            # Prune dead registrations so a patient with rotated tokens does
            # not silently stop receiving everything forever.
            if invalid_tokens:
                token_to_device = {d.fcm_token: d.device_id for d in devices if d.fcm_token}
                for token in invalid_tokens:
                    device_id = token_to_device.get(token)
                    if device_id:
                        try:
                            await user_device_service.delete_user_device(device_id)
                        except Exception as prune_exc:
                            logger.warning(f"Failed to prune dead FCM token: {prune_exc}")

            logger.info(
                f"Notification batch completed for user {user_id}: "
                f"{response.success_count} success, {response.failure_count} failure(s)"
            )
            if response.success_count == 0:
                # Every device failed — surface it instead of reporting a
                # delivered notification that nobody received.
                raise RuntimeError(
                    f"All {len(tokens)} FCM sends failed for user {user_id}"
                )

        except Exception as e:
            logger.error(f"Failed to send batch notifications to user {user_id}: {e}")
            raise

    async def send_fcm_data_to_user_devices(
        self,
        user_id: str,
        data: dict,
    ) -> None:
        """Send a SILENT data-only message to all of a user's devices.

        No notification payload — nothing appears in the tray. Used to tell
        a foregrounded app that server-side state changed (e.g. a chat thread
        gained a turn or a translation) so open screens refresh live.
        """
        try:
            postgres_store = cast(PostgresStore, container.resolve(PostgresStore))
            user_device_service = UserDeviceService(postgres_store=postgres_store)
            devices = await user_device_service.get_user_devices(user_id=UUID(user_id))
            tokens = [d.fcm_token for d in devices if d.fcm_token]
            if not tokens:
                return

            message = messaging.MulticastMessage(
                tokens=tokens,
                data={k: str(v) for k, v in data.items()},
                android=messaging.AndroidConfig(priority="high"),
                apns=messaging.APNSConfig(
                    payload=messaging.APNSPayload(
                        aps=messaging.Aps(content_available=True),
                    ),
                ),
            )
            response = await asyncio.to_thread(
                messaging.send_each_for_multicast, message
            )
            logger.debug(
                "Silent data message to %s: %d ok, %d failed",
                user_id, response.success_count, response.failure_count,
            )
        except Exception as e:
            # Best-effort: a missed refresh signal degrades to refresh-on-reopen.
            logger.warning(f"Failed to send data message to user {user_id}: {e}")
