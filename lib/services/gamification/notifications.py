"""Shared FCM helper for gamification milestone notifications."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def send_gamification_notification(
    patient_id: str,
    *,
    title: str,
    body: str,
    data: dict[str, Any] | None = None,
) -> None:
    try:
        from lib.services.fcm_service import FCMService

        await FCMService().send_fcm_notification_to_user_devices(
            user_id=patient_id,
            title=title,
            body=body,
            channel_key="gamification",
            group_key="gamification_group",
            data={"type": "gamification", **(data or {})},
        )
    except Exception as exc:
        logger.warning("Failed gamification notification for %s: %s", patient_id, exc)
