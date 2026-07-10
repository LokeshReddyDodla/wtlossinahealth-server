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
    trigger: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    event_time: str | None = None,
    chat_continuation: bool = False,
    thread_id: str | None = None,
) -> None:
    """Send FCM push for the top-severity insight and record it."""
    if not insights:
        return
    target = notification_target or patient_id
    top = max(insights, key=lambda i: SEVERITY_RANK.get(i.severity.value, 0))
    is_urgent = top.severity.value in ("warning", "alert")

    is_event = trigger is not None

    if not is_event:
        from lib.services.notification_budget import can_send, record_sent

        notif_type = "health_alert" if is_urgent else "health_insight"
        if not can_send(target, notif_type):
            logger.info("Notification budget exceeded for %s, skipping %s", target, notif_type)
            return

    try:
        await fcm.send_fcm_notification_to_user_devices(
            user_id=target,
            title=top.title,
            body=top.body,
            channel_key="alerts" if is_urgent else "health_insights",
            group_key="alert_group" if is_urgent else "health_insights_group",
            data={
                "type": "proactive_insight",
                "insight_id": top.insight_id,
                "category": top.category.value,
                "severity": top.severity.value,
                "patient_id": patient_id,
                "suggested_query": top.suggested_query or "",
                "total_insights": str(len(insights)),
                # Source-event linkage + chat routing (companion Phase 3).
                # route=chat means: this insight continues the health-agent
                # conversation — open the chat, not the insights list.
                "entity_type": entity_type or "",
                "entity_id": entity_id or "",
                "route": "chat" if chat_continuation else "",
                "thread_id": thread_id or "",
            },
        )
        if not is_event:
            record_sent(target)
        await monitor.record_insight(
            patient_id, top, trigger=trigger,
            entity_type=entity_type, entity_id=entity_id,
            event_time=event_time,
        )
    except Exception as e:
        logger.warning("Failed to send notification for %s: %s", patient_id, e)
