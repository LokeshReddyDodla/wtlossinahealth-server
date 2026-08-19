"""Event-driven proactive scan task.

Triggered by data-ingestion worker tasks (meal vectorization, CGM threshold
crossings, etc.). Validates the trigger + anchor at the arq boundary, then
delegates to ProactiveMonitorAgent.scan_patient(trigger=..., anchor=...).
"""

from __future__ import annotations

from typing import Any

from loguru import logger
from pydantic import ValidationError
from sqlalchemy import update

from lib.ai_foundation.agents.core.patient_resolver import PatientNameResolver
from lib.ai_foundation.agents.proactive_monitor import ProactiveMonitorAgent
from lib.ai_foundation.agents.proactive_monitor.contracts import (
    BETA_TITLE_PREFIX,
    EventTrigger,
    MealLoggedAnchor,
    SMBGLoggedAnchor,
    SymptomLoggedAnchor,
    SEVERITY_RANK,
    TRIGGER_DATA_TYPES,
    TriggerAnchor,
    parse_anchor,
)
from lib.ai_foundation.agents.proactive_monitor.notify import (
    send_top_insight_notification,
)
from lib.core.container import container
from lib.ai_foundation.config import settings
from lib.services.fcm_service import FCMService
from lib.workers.tasks.base import TaskResult, task_with_logging


def _extract_entity(anchor: TriggerAnchor) -> tuple[str | None, str | None]:
    """Extract (entity_type, entity_id) from a typed anchor."""
    if isinstance(anchor, MealLoggedAnchor):
        return "meal", anchor.meal_id
    if isinstance(anchor, SMBGLoggedAnchor):
        return "smbg", anchor.reading_id
    if isinstance(anchor, SymptomLoggedAnchor):
        return "symptom", anchor.symptom_entry_id
    return None, None


def _is_stale_event(anchor: Any) -> bool:
    """True if the anchor's source event is older than the freshness window
    (a backfilled log, not something that just happened). Unknown/unparseable
    time → False (fresh) so we never suppress on uncertainty."""
    from datetime import datetime, timezone

    raw = getattr(anchor, "event_time", None)
    if not raw:
        return False
    try:
        ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age_h = (datetime.now(timezone.utc) - ts).total_seconds() / 3600
        return age_h > settings.EVENT_FRESHNESS_HOURS
    except Exception:
        return False


@task_with_logging
async def handle_proactive_event(
    ctx: dict[str, Any],
    patient_id: str,
    trigger: str,
    anchor: dict[str, Any] | None = None,
) -> TaskResult:
    """Run an event-driven proactive scan for a single patient.

    ``trigger`` is the string value of an ``EventTrigger`` (arq serialises
    enums as their value). ``anchor`` is a JSON-friendly dict that we
    validate into the right typed model immediately.
    """
    try:
        trigger_enum = EventTrigger(trigger)
    except ValueError:
        return TaskResult(
            success=False,
            error=f"Unknown trigger: {trigger}",
            data={"patient_id": patient_id, "trigger": trigger},
        )

    try:
        typed_anchor = parse_anchor(trigger_enum, anchor)
    except ValidationError as exc:
        logger.warning(
            "handle_proactive_event: invalid anchor for %s (%s): %s",
            patient_id, trigger, exc,
        )
        return TaskResult(
            success=False,
            error=f"Invalid anchor for trigger {trigger}",
            data={"patient_id": patient_id, "trigger": trigger},
        )

    # Freshness gate: a patient backfilling an old meal/reading is NOT a live
    # moment — react only to events that actually just happened, so a bulk
    # catch-up doesn't fire a burst of "just now" pushes. Missing/unparseable
    # event_time → treat as fresh (don't suppress on uncertainty).
    if _is_stale_event(typed_anchor):
        logger.info("handle_proactive_event: stale %s for %s — skipping push", trigger, patient_id[:8])
        return TaskResult(
            success=True, data={"patient_id": patient_id, "trigger": trigger, "skipped": "stale_event"},
        )

    try:
        monitor = container.resolve(ProactiveMonitorAgent)
        resolver = container.resolve(PatientNameResolver)

        names = await resolver.resolve_names([patient_id])
        tzs = await resolver.resolve_timezones([patient_id])
        language = await resolver.resolve_language(patient_id)

        result = await monitor.scan_patient(
            patient_id=patient_id,
            patient_name=names.get(patient_id),
            tz_name=tzs.get(patient_id),
            trigger=trigger_enum,
            anchor=typed_anchor,
        )

        if result.error:
            return TaskResult(
                success=False,
                error=result.error,
                data={"patient_id": patient_id, "trigger": trigger},
            )

        entity_type, entity_id = _extract_entity(typed_anchor)
        thread_id = f"bot:patient:{patient_id}"

        if result.insights:
            for ins in result.insights:
                ins.title = f"{BETA_TITLE_PREFIX}{ins.title}"
            top = max(result.insights, key=lambda i: SEVERITY_RANK.get(i.severity.value, 0))
            await _save_insight_to_record(typed_anchor, top.body)

            # Companion Phase 3: if the health agent asked the user to log
            # exactly this kind of data, this insight CONTINUES that chat —
            # post it into the thread and route the push to the conversation.
            # The chat turn shows the preferred language; English rides along.
            chat_body, english_body = await _localize(top.body, language)
            continuation = await _consume_pending_request(
                thread_id, entity_type, chat_body,
                language=language, english_body=english_body,
            )

            await send_top_insight_notification(
                patient_id, result.insights, monitor, FCMService(),
                trigger=trigger,
                entity_type=entity_type,
                entity_id=entity_id,
                event_time=typed_anchor.event_time,
                chat_continuation=continuation,
                thread_id=thread_id if continuation else None,
                # already translated for the chat turn — push reuses it
                body_translation=chat_body if english_body else None,
            )
        else:
            # The agent asked for this data and the user delivered — never
            # answer that with silence, even when the scan has nothing to say.
            ack_shown, ack_english = await _localize(
                _ack_body(entity_type), language, cached=True,
            )
            await _consume_pending_request(
                thread_id, entity_type, ack_shown,
                language=language, english_body=ack_english,
            )

        return TaskResult(
            success=True,
            data={
                "patient_id": patient_id,
                "trigger": trigger,
                "insight_count": len(result.insights),
                "alert_count": result.alert_count,
                "scan_duration_ms": result.scan_duration_ms,
                "data_types_fetched": [
                    dt.value for dt in TRIGGER_DATA_TYPES.get(trigger_enum, [])
                ],
            },
        )

    except Exception as exc:
        logger.error(
            "handle_proactive_event failed for %s trigger=%s: %s",
            patient_id, trigger, exc,
        )
        return TaskResult(
            success=False,
            error=str(exc),
            data={"patient_id": patient_id, "trigger": trigger},
        )


# Canonical English — non-English users get these through the
# TranslationService (cached), same path as every other AI string.
_ACK_WORDS = {
    "meal": "meal", "smbg": "glucose reading", "symptom": "symptom note",
    "sleep": "sleep log", "mood": "check-in", "workout": "workout",
}


def _ack_body(entity_type: str | None) -> str:
    word = _ACK_WORDS.get(entity_type or "", "log")
    return (
        f"Got your {word} — thanks for logging it. Nothing stands out right now, "
        "but I'm keeping an eye on things and I'll flag anything worth knowing."
    )


async def _localize(
    body: str, language: str, *, cached: bool = False,
) -> tuple[str, str | None]:
    """Return (text shown in chat, English original when translated).

    ``cached=True`` for fixed strings (the ack) — a tiny recurring set.
    """
    if language == "en":
        return body, None
    try:
        from lib.ai_foundation.translation import TranslationService

        translator = container.resolve(TranslationService)
        if cached:
            translated = await translator.translate_cached(body, language)
        else:
            translated = await translator.translate(body, language)
        return translated, body
    except Exception as exc:
        logger.warning("Chat-continuation translation failed: %s", exc)
        return body, None


async def _consume_pending_request(
    thread_id: str, entity_type: str | None, insight_body: str,
    *, language: str = "en", english_body: str | None = None,
) -> bool:
    """Close the ask→log→analyze loop.

    If the chat thread has a live pending_data_request matching this event's
    entity type: append the insight as the agent's next conversation turn,
    clear the request, and return True (caller routes the push to chat).

    ``insight_body`` is what the user sees (their preferred language);
    ``english_body`` carries the English original when they differ.
    """
    if not entity_type:
        return False
    try:
        from datetime import datetime, timezone

        from lib.ai_foundation.memory.base import ConversationTurn
        from lib.ai_foundation.memory.mongo_store import MongoMemoryStore

        memory = container.resolve(MongoMemoryStore)
        summary = await memory.get_thread_summary(thread_id)
        pending = summary.pending_data_request if summary else None
        if not pending or pending.get("entity_type") != entity_type:
            return False
        try:
            expired = datetime.fromisoformat(pending["expires_at"]) <= datetime.now(timezone.utc)
        except Exception:
            expired = True
        if expired:
            # Stale ask — clear it (partial $set: don't touch other fields).
            await memory.update_thread_summary_fields(
                thread_id, {"pending_data_request": None},
            )
            return False

        # Append the reply FIRST, clear the pending after: if the append
        # fails, the ask must survive for the next event. Worst case is a
        # duplicate reply — never an unanswered ask.
        turn_metadata: dict = {"kind": "data_request_followup", "entity_type": entity_type}
        if language != "en" and english_body:
            turn_metadata["language"] = language
            turn_metadata["translations"] = {"en": english_body}
        await memory.append_turns_batch(thread_id, [ConversationTurn(
            role="assistant",
            content=insight_body,
            agent_id="proactive_monitor_v2",
            metadata=turn_metadata,
        )])
        await memory.update_thread_summary_fields(
            thread_id, {"pending_data_request": None},
        )
        # Nudge an open chat to refresh live (silent data message) — the
        # visible push is the doorbell for a closed app; this covers the
        # common case of the user still sitting in the conversation.
        try:
            from lib.services.fcm_service import FCMService

            patient_id = thread_id.rsplit(":", 1)[-1]
            await FCMService().send_fcm_data_to_user_devices(
                user_id=patient_id,
                data={"type": "chat_thread_updated", "thread_id": thread_id,
                      "reason": "continuation"},
            )
        except Exception as exc:
            logger.debug("chat_thread_updated nudge failed: %s", exc)
        logger.info("Chat continuation: %s fulfilled pending %s request", thread_id, entity_type)
        return True
    except Exception as exc:
        logger.warning("pending-request continuation failed (%s): %s", thread_id, exc)
        return False


async def _save_insight_to_record(anchor: Any, body: str) -> None:
    """Write the AI insight body back to the source meal row."""
    from lib.dependencies.database import postgres_store
    from lib.models.patient_meal import PatientMeal

    if isinstance(anchor, MealLoggedAnchor):
        stmt = (
            update(PatientMeal)
            .where(PatientMeal.id == anchor.meal_id)
            .values(ai_insight=body)
        )
    else:
        return

    try:
        async with postgres_store.get_session() as session:
            await session.execute(stmt)
            await session.commit()
    except Exception as exc:
        logger.warning("Failed to save ai_insight to record: %s", exc)
