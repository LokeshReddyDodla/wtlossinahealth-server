"""ARQ tasks for InBody contextual insights.

Enqueued when a report's extraction lands ``extracted``. On LLM failure the
job re-enqueues itself with backoff — there is no fallback text by design;
the notification only ever carries a real generated insight.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict
from uuid import UUID

from loguru import logger

from lib.workers.tasks.base import task_with_logging

INSIGHT_RETRY_DELAYS_MINUTES = [5, 15, 30]
INSIGHT_MAX_ATTEMPTS = 10


@task_with_logging
async def run_inbody_insight(
    ctx: Dict[str, Any], report_id: str, attempt: int = 1
) -> None:
    from lib.dependencies.service_dependencies import (
        get_inbody_insight_service,
    )
    from lib.workers.arq.redis import enqueue_job

    service = get_inbody_insight_service()

    try:
        insight_doc = await service.generate_insight(UUID(report_id))
    except Exception as exc:
        if attempt >= INSIGHT_MAX_ATTEMPTS:
            logger.error(
                f"❌ InBody insight exhausted retries report={report_id} "
                f"attempts={attempt}: {exc}"
            )
            return
        delay_index = min(attempt, len(INSIGHT_RETRY_DELAYS_MINUTES)) - 1
        delay = timedelta(minutes=INSIGHT_RETRY_DELAYS_MINUTES[delay_index])
        logger.warning(
            f"⚠️ InBody insight failed report={report_id} attempt={attempt}; "
            f"retrying in {delay} — {exc}"
        )
        await enqueue_job(
            "run_inbody_insight",
            report_id,
            attempt + 1,
            _defer_by=delay,
            _job_id=f"inbody-insight-{report_id}-a{attempt + 1}",
        )
        return

    await _notify_patient(insight_doc)


async def _notify_patient(insight_doc: Dict[str, Any]) -> None:
    """One push per completed insight, through the standard pipeline."""

    insight = insight_doc.get("insight") or {}
    patient_id = insight_doc.get("patient_id")
    report_id = insight_doc.get("report_id")
    if not insight or not patient_id:
        return
    # Re-runs of a completed insight (force/regenerate) must not re-notify.
    if insight_doc.get("notified_at"):
        return

    from lib.services import notification_budget
    from lib.services.notifications.sender import record_and_send_notification

    if not notification_budget.can_send(patient_id, "inbody_insight"):
        logger.info(
            f"inbody-insight: notification budget exhausted patient={patient_id}"
            " — insight stored, push skipped"
        )
        return

    await record_and_send_notification(
        patient_id,
        category="inbody_insight",
        title=insight.get("notification_title") or "Your InBody results are in",
        body=insight.get("notification_body")
        or "Your new scan has been analyzed — see what changed.",
        severity="info",
        deeplink=f"aihealth://inbody/reports/{report_id}",
        data={"report_id": str(report_id)},
    )
    notification_budget.record_sent(patient_id)

    from lib.dependencies.service_dependencies import (
        get_inbody_insight_service,
    )
    from datetime import datetime, timezone

    service = get_inbody_insight_service()
    await service.insights_collection.update_one(
        {"report_id": str(report_id)},
        {"$set": {"notified_at": datetime.now(timezone.utc)}},
    )
    logger.info(f"✅ InBody insight notification sent patient={patient_id}")
