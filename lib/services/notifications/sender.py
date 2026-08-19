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
from lib.core.types import (
    FCMNotificationChannelKeyLiteral,
    FCMNotificationGroupKeyLiteral,
    NotificationCategoryLiteral,
    NotificationSeverityLiteral,
)

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


# (channel, group, broker-category) for each legacy sender category. The
# broker's policy.py decides tier/limit/mute from the broker-category.
_CATEGORY_ROUTE: dict[
    NotificationCategoryLiteral,
    tuple[FCMNotificationChannelKeyLiteral, FCMNotificationGroupKeyLiteral, str],
] = {
    "gamification": ("gamification", "gamification_group", "gamification"),
    "medication_lifecycle": ("reminders", "reminder_group", "medication_lifecycle"),
    "medication_refill": ("reminders", "reminder_group", "refill_reminder"),
    "medication_dose": ("reminders", "reminder_group", "medication_dose"),
    "follow_up": ("reminders", "reminder_group", "follow_up_reminder"),
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
) -> UUID | None:
    """Send a reminder/gamification push through the notification broker.

    Thin adapter kept for the existing callers — the broker now owns the
    delivery decision (tier policy, per-category budget, mute, quiet hours,
    translation, inbox row, FCM). Returns the inbox row id, or None if the
    broker suppressed or failed to persist.
    """
    from lib.services.notifications.broker import deliver

    channel_key, group_key, broker_category = _CATEGORY_ROUTE[category]
    result = await deliver(
        patient_id,
        category=broker_category,
        title=title,
        body=body,
        channel_key=channel_key,
        group_key=group_key,
        data=data or {},
        severity=severity,
        deeplink=deeplink,
        force=skip_permission_check,
    )
    return result.notification_id
