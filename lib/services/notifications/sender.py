"""Central helper for patient notifications.

Every feature that sends a push to a patient goes through
``record_and_send_notification``. The helper persists the notification
row first, then fires FCM — so a failed push still leaves an inbox
record for the patient to see.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from lib.core.container import container
from lib.core.postgres_store import PostgresStore
from lib.core.types import (
    FCMNotificationChannelKeyLiteral,
    FCMNotificationGroupKeyLiteral,
    NotificationCategoryLiteral,
    NotificationSeverityLiteral,
)
from lib.models.patient_notification import PatientNotification

logger = logging.getLogger(__name__)


_CATEGORY_CHANNEL: dict[
    NotificationCategoryLiteral,
    tuple[FCMNotificationChannelKeyLiteral, FCMNotificationGroupKeyLiteral],
] = {
    "gamification": ("gamification", "gamification_group"),
    "medication_lifecycle": ("reminders", "reminder_group"),
    "medication_refill": ("reminders", "reminder_group"),
    "medication_dose": ("reminders", "reminder_group"),
    "follow_up": ("reminders", "reminder_group"),
}


async def record_and_send_notification(
    patient_id: str,
    *,
    category: NotificationCategoryLiteral,
    title: str,
    body: str,
    severity: Optional[NotificationSeverityLiteral] = None,
    deeplink: Optional[str] = None,
    data: Optional[dict[str, Any]] = None,
    skip_permission_check: bool = False,
) -> UUID:
    """Persist the notification then fire FCM.

    Returns the ``patient_notifications.id`` so callers can reference it
    (e.g. for deeplink construction). FCM failures are logged but don't
    raise — the inbox row is the user's source of truth.
    """
    data = data or {}
    channel_key, group_key = _CATEGORY_CHANNEL[category]

    store = container.resolve(PostgresStore)
    now = datetime.now().replace(tzinfo=None)

    notif = PatientNotification(
        patient_id=UUID(patient_id),
        category=category,
        title=title,
        body=body,
        severity=severity,
        deeplink=deeplink,
        data=data,
        sent_at=now,
        created_at=now,
    )

    async with store.get_session() as session:
        session.add(notif)
        await session.commit()
        await session.refresh(notif)

    fcm_data = {
        "notification_id": str(notif.id),
        "category": category,
        **data,
    }

    try:
        from lib.services.fcm_service import FCMService

        await FCMService().send_fcm_notification_to_user_devices(
            user_id=patient_id,
            title=title,
            body=body,
            channel_key=channel_key,
            group_key=group_key,
            data=fcm_data,
            skip_permission_check=skip_permission_check,
        )
    except Exception as exc:
        logger.warning(
            "FCM send failed for notification %s (patient %s, category %s): %s",
            notif.id,
            patient_id,
            category,
            exc,
        )

    return notif.id
