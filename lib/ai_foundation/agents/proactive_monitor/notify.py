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

    # Preferred AI language: the user sees the translated push; the English
    # original stays on the insight record (audit invariant).
    translation = await _translate_for_target(target, top)
    push_title = translation["title"] if translation else top.title
    push_body = translation["message"] if translation else top.body
    push_query = translation["suggested_query"] if translation else (top.suggested_query or "")

    # Record BEFORE sending: a recorded-but-unsent insight self-heals (next
    # scan dedups against it and can resend); a sent-but-unrecorded one
    # double-pushes the patient and leaves a dangling insight_id in the app.
    try:
        await monitor.record_insight(
            patient_id, top, trigger=trigger,
            entity_type=entity_type, entity_id=entity_id,
            event_time=event_time,
            translation=translation,
        )
    except Exception as e:
        logger.warning("Failed to record insight for %s: %s", patient_id, e)

    try:
        await fcm.send_fcm_notification_to_user_devices(
            user_id=target,
            title=push_title,
            body=push_body,
            channel_key="alerts" if is_urgent else "health_insights",
            group_key="alert_group" if is_urgent else "health_insights_group",
            data={
                "type": "proactive_insight",
                "insight_id": top.insight_id,
                "category": top.category.value,
                "severity": top.severity.value,
                "patient_id": patient_id,
                "suggested_query": push_query,
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
    except Exception as e:
        logger.warning("Failed to send notification for %s: %s", patient_id, e)


async def _translate_for_target(target: str, top: HealthInsight) -> dict | None:
    """Return {"language", "title", "message", "suggested_query"} in the
    target's preferred AI language, or None for English/on any failure."""
    try:
        import asyncio

        from lib.core.container import container
        from lib.ai_foundation.agents.core.patient_resolver import PatientNameResolver
        from lib.ai_foundation.translation import TranslationService
        from lib.core.types import DEFAULT_AI_LANGUAGE

        resolver = container.resolve(PatientNameResolver)
        language = await resolver.resolve_language(target)
        if language == DEFAULT_AI_LANGUAGE:
            return None
        translator = container.resolve(TranslationService)
        title, message, query = await asyncio.gather(
            translator.translate(top.title, language),
            translator.translate(top.body, language),
            translator.translate(top.suggested_query or "", language),
        )
        return {
            "language": language,
            "title": title,
            "message": message,
            "suggested_query": query,
        }
    except Exception as exc:
        logger.warning("Insight translation failed for %s: %s", target, exc)
        return None
