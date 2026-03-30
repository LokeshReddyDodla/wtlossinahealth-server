"""Shared notification helper for proactive monitor insights."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from lib.ai_foundation.agents.proactive_monitor.contracts import HealthInsight

from lib.ai_foundation.agents.proactive_monitor.contracts import SEVERITY_RANK

logger = logging.getLogger(__name__)


async def send_top_insight_notification(
    patient_id: str,
    insights: list[HealthInsight],
    monitor: Any,
    fcm: Any,
    *,
    notification_target: str | None = None,
) -> None:
    """Send FCM push for the top-severity insight and record it."""
    if not insights:
        return
    target = notification_target or patient_id
    top = max(insights, key=lambda i: SEVERITY_RANK.get(i.severity.value, 0))
    is_urgent = top.severity.value in ("warning", "alert")

    try:
        await fcm.send_fcm_notification_to_user_devices(
            user_id=target,
            title=top.title,
            body=top.body,
            channel_key="alerts" if is_urgent else "reminders",
            group_key="alert_group" if is_urgent else "reminder_group",
            data={
                "type": "proactive_insight",
                "insight_id": top.insight_id,
                "category": top.category.value,
                "severity": top.severity.value,
                "patient_id": patient_id,
                "suggested_query": top.suggested_query or "",
                "total_insights": str(len(insights)),
            },
        )
        # Only the top-severity insight is persisted — others are discarded by design.
        await monitor.record_insight(patient_id, top)
    except Exception as e:
        logger.warning("Failed to send notification for %s: %s", patient_id, e)
