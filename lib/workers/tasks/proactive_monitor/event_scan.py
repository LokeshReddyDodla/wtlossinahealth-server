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
    EventTrigger,
    MealLoggedAnchor,
    SMBGLoggedAnchor,
    SymptomLoggedAnchor,
    MedicationMissedAnchor,
    SEVERITY_RANK,
    TRIGGER_DATA_TYPES,
    TriggerAnchor,
    parse_anchor,
)
from lib.ai_foundation.agents.proactive_monitor.notify import (
    send_top_insight_notification,
)
from lib.core.container import container
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
    if isinstance(anchor, MedicationMissedAnchor):
        return "medication_task", anchor.daily_task_id
    return None, None


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

    try:
        monitor = container.resolve(ProactiveMonitorAgent)
        resolver = container.resolve(PatientNameResolver)

        names = await resolver.resolve_names([patient_id])
        tzs = await resolver.resolve_timezones([patient_id])

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

        if result.insights:
            for ins in result.insights:
                ins.title = f"[Beta] {ins.title}"
            top = max(result.insights, key=lambda i: SEVERITY_RANK.get(i.severity.value, 0))
            await _save_insight_to_record(typed_anchor, top.body)
            entity_type, entity_id = _extract_entity(typed_anchor)

            # Companion Phase 3: if the health agent asked the user to log
            # exactly this kind of data, this insight CONTINUES that chat —
            # post it into the thread and route the push to the conversation.
            thread_id = f"bot:patient:{patient_id}"
            continuation = await _consume_pending_request(thread_id, entity_type, top.body)

            await send_top_insight_notification(
                patient_id, result.insights, monitor, FCMService(),
                trigger=trigger,
                entity_type=entity_type,
                entity_id=entity_id,
                event_time=typed_anchor.event_time,
                chat_continuation=continuation,
                thread_id=thread_id if continuation else None,
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


async def _consume_pending_request(
    thread_id: str, entity_type: str | None, insight_body: str,
) -> bool:
    """Close the ask→log→analyze loop.

    If the chat thread has a live pending_data_request matching this event's
    entity type: append the insight as the agent's next conversation turn,
    clear the request, and return True (caller routes the push to chat).
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
        # Clear the request either way — fulfilled or stale, it's done.
        summary.pending_data_request = None
        await memory.save_thread_summary(thread_id, summary)
        if expired:
            return False

        await memory.append_turns_batch(thread_id, [ConversationTurn(
            role="assistant",
            content=insight_body,
            agent_id="proactive_monitor_v2",
            metadata={"kind": "data_request_followup", "entity_type": entity_type},
        )])
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
