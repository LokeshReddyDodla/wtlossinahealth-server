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
    body_translation: str | None = None,
) -> None:
    """Send FCM push for the top-severity insight and record it.

    ``body_translation``: the body already translated for this patient by the
    caller (the event scan translates it for the chat turn) — reused here so
    the push and the chat message can't diverge and we don't pay twice.
    """
    if not insights:
        return
    target = notification_target or patient_id
    top = max(insights, key=lambda i: SEVERITY_RANK.get(i.severity.value, 0))
    is_urgent = top.severity.value in ("warning", "alert")

    is_event = trigger is not None

    # Preferred AI language: the user sees the translated push; the English
    # original stays on the insight record (audit invariant).
    translation = await _translate_for_target(
        target, top,
        body_translation=body_translation if target == patient_id else None,
    )
    push_title = translation["title"] if translation else top.title
    push_body = translation["message"] if translation else top.body
    push_query = translation["suggested_query"] if translation else (top.suggested_query or "")

    # Record before sending: a recorded-but-unsent insight is retried next
    # scan; a sent-but-unrecorded one double-pushes and leaves a dangling id.
    try:
        await monitor.record_insight(
            patient_id, top, trigger=trigger,
            entity_type=entity_type, entity_id=entity_id,
            event_time=event_time,
            translation=translation,
        )
    except Exception as e:
        logger.warning("Failed to record insight for %s: %s", patient_id, e)

    # Delivery goes through the broker: EVENT insights (a trigger fired) are
    # unlimited and ignore quiet hours; unprompted cron insights are the
    # PROACTIVE tier (per-category cap + quiet hours + mute). Title/body are
    # already in the patient's language, so the broker doesn't re-translate.
    from lib.services.notifications.broker import deliver

    broker_category = _broker_category(trigger, is_urgent)
    await deliver(
        target,
        category=broker_category,
        title=push_title,
        body=push_body,
        channel_key="alerts" if is_urgent else "health_insights",
        group_key="alert_group" if is_urgent else "health_insights_group",
        severity=top.severity.value,
        prelocalized=True,
        record_inbox=False,  # insights live in the insight store, not the inbox
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


def _broker_category(trigger: str | None, is_urgent: bool) -> str:
    """Map a scan to a broker policy category. A safety-urgent event is
    CRITICAL (unmutable); a normal event is its own EVENT-tier category;
    an unprompted cron insight is PROACTIVE."""
    if trigger is None:
        return "proactive_insight"
    if is_urgent:
        return "safety_alert"
    # Event categories mirror the trigger names in policy.py
    return trigger if trigger in {
        "meal_logged", "smbg_logged", "symptom_logged",
        "cgm_threshold_crossed", "medication_missed",
    } else "proactive_insight"


async def _translate_for_target(
    target: str, top: HealthInsight, *, body_translation: str | None = None,
) -> dict | None:
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

        # Product markers like "[Beta]" stay verbatim — translate only the title text.
        from lib.ai_foundation.agents.proactive_monitor.contracts import BETA_TITLE_PREFIX

        title_prefix = ""
        title_text = top.title
        if title_text.startswith(BETA_TITLE_PREFIX):
            title_prefix, title_text = BETA_TITLE_PREFIX, title_text[len(BETA_TITLE_PREFIX):]

        async def _body() -> str:
            return body_translation or await translator.translate(top.body, language)

        title, message, query = await asyncio.gather(
            translator.translate(title_text, language),
            _body(),
            translator.translate(top.suggested_query or "", language),
        )
        return {
            "language": language,
            "title": f"{title_prefix}{title}",
            "message": message,
            "suggested_query": query,
        }
    except Exception as exc:
        logger.warning("Insight translation failed for %s: %s", target, exc)
        return None
