"""Shared FCM helper for gamification milestone notifications.

Persists an inbox row via the central helper, then fires FCM.
"""

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
        from lib.services.notifications import record_and_send_notification

        await record_and_send_notification(
            patient_id,
            category="gamification",
            title=title,
            body=body,
            data=data or {},
        )
    except Exception as exc:
        logger.warning("Failed gamification notification for %s: %s", patient_id, exc)
