"""Central helper for patient notifications.

Every feature that sends a push to a patient goes through
``record_and_send_notification``. The helper persists the notification
row first, then fires FCM — so a failed push still leaves an inbox
record for the patient to see.
"""

from __future__ import annotations

import logging
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


async def localize_for_patient(patient_id: str, title: str, body: str) -> tuple[str, str]:
    """Translate title/body into the patient's preferred AI language.

    Titles are near-fixed strings (cached translation); bodies carry
    patient-specific content (uncached). Any failure returns the English
    originals.
    """
    try:
        import asyncio

        from lib.ai_foundation.agents.core.patient_resolver import PatientNameResolver
        from lib.ai_foundation.translation import TranslationService
        from lib.core.types import DEFAULT_AI_LANGUAGE

        resolver = container.resolve(PatientNameResolver)
        language = await resolver.resolve_language(patient_id)
        if language == DEFAULT_AI_LANGUAGE:
            return title, body
        translator = container.resolve(TranslationService)
        return tuple(await asyncio.gather(
            translator.translate_cached(title, language),
            translator.translate(body, language),
        ))
    except Exception as exc:
        logger.warning("Notification translation failed for %s: %s", patient_id, exc)
        return title, body


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

    # The language invariant applies to EVERY patient-facing surface: the
    # inbox row and the push must both arrive in the preferred AI language.
    # English is canonical in code; delivery translates. Fail-open — an
    # English push beats no push.
    title, body = await localize_for_patient(patient_id, title, body)

    store = container.resolve(PostgresStore)

    notif = PatientNotification(
        patient_id=UUID(patient_id),
        category=category,
        title=title,
        body=body,
        severity=severity,
        deeplink=deeplink,
        data=data,
    )

    # created_at is set by Postgres server_default=now() — single clock source
    # so timestamps stay consistent across worker processes and containers.
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
