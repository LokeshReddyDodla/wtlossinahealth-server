"""Event-driven proactive scan task.

Triggered by data-ingestion worker tasks (meal vectorization, CGM threshold
crossings, etc.). Validates the trigger + anchor at the arq boundary, then
delegates to ProactiveMonitorAgent.scan_patient(trigger=..., anchor=...).
"""

from __future__ import annotations

from typing import Any

from loguru import logger
from pydantic import ValidationError

from lib.ai_foundation.agents.core.patient_resolver import PatientNameResolver
from lib.ai_foundation.agents.proactive_monitor import ProactiveMonitorAgent
from lib.ai_foundation.agents.proactive_monitor.contracts import (
    EventTrigger,
    TRIGGER_DATA_TYPES,
    parse_anchor,
)
from lib.ai_foundation.agents.proactive_monitor.notify import (
    send_top_insight_notification,
)
from lib.core.container import container
from lib.services.fcm_service import FCMService
from lib.workers.tasks.base import TaskResult, task_with_logging


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
            await send_top_insight_notification(
                patient_id, result.insights, monitor, FCMService(),
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
