"""
Proactive Monitor Worker Task — runs patient health scans on a cron schedule.

Designed to be registered as an arq cron job. Fetches active patient IDs
and runs the ProactiveMonitorAgent.scan_batch() pipeline.

Includes timezone-aware scheduling: patients are only scanned between 7 AM
and 10 PM in their local timezone (defaults to Asia/Kolkata).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from loguru import logger

from lib.ai_foundation.agents.proactive_monitor.contracts import SEVERITY_RANK
from lib.ai_foundation.agents.proactive_monitor.scheduling import (
    DEFAULT_TIMEZONE,
    is_within_scan_window,
)
from lib.workers.tasks.base import TaskResult, task_with_logging

# Skip patients who signed up less than this many days ago
_MIN_HISTORY_DAYS = 3


# ---------------------------------------------------------------------------
# Task entry points
# ---------------------------------------------------------------------------


@task_with_logging
async def run_proactive_scan(
    ctx: dict[str, Any],
    patient_ids: list[str] | None = None,
) -> TaskResult:
    """Scan patients for proactive health insights.

    If patient_ids is None, scans all active patients (active device in last 7 days).
    Patients outside their local scan window (7 AM - 10 PM) are skipped.
    """
    try:
        from lib.core.container import container
        from lib.ai_foundation.agents.proactive_monitor import ProactiveMonitorAgent
        from lib.ai_foundation.agents.health_query.patient_resolver import PatientNameResolver

        monitor = container.resolve(ProactiveMonitorAgent)
        resolver = container.resolve(PatientNameResolver)

        # 1. Get active patients (from UserDevice, not meal_reports)
        if not patient_ids:
            patient_ids = await _get_active_patient_ids()
        if not patient_ids:
            return TaskResult(success=True, data={"message": "No active patients to scan"})

        # 2. Batch-resolve names + timezones (single query, cached 5 min)
        all_names = await resolver.resolve_names(patient_ids)
        all_timezones = await resolver.resolve_timezones(patient_ids)

        # 3. Filter: scan window + minimum history
        eligible_ids, skipped = _filter_by_scan_window(patient_ids, all_timezones)

        if skipped:
            logger.info("Timezone filter: %d/%d patients outside scan window", skipped, len(patient_ids))
        if not eligible_ids:
            return TaskResult(
                success=True,
                data={"message": "All patients outside scan window", "total": len(patient_ids), "skipped_timezone": skipped},
            )

        # 4. Scan eligible patients
        patient_names = {pid: all_names[pid] for pid in eligible_ids if pid in all_names}
        patient_timezones = {pid: all_timezones.get(pid, DEFAULT_TIMEZONE) for pid in eligible_ids}

        batch = await monitor.scan_batch(eligible_ids, patient_names=patient_names, patient_timezones=patient_timezones)

        # 5. Send notifications
        for result in batch.results:
            if result.insights:
                await _send_notification(result.patient_id, result.insights, monitor)

        return TaskResult(
            success=True,
            data={
                "scanned": batch.scanned,
                "with_insights": batch.with_insights,
                "total_insights": batch.total_insights,
                "total_alerts": batch.total_alerts,
                "errors": batch.errors,
                "duration_ms": batch.duration_ms,
                "skipped_timezone": skipped,
            },
        )
    except Exception as e:
        logger.error(f"Proactive scan failed: {e}")
        return TaskResult(success=False, error=str(e))


@task_with_logging
async def run_proactive_scan_single(
    ctx: dict[str, Any],
    patient_id: str,
) -> TaskResult:
    """Scan a single patient. Useful for event-triggered scans."""
    try:
        from lib.core.container import container
        from lib.ai_foundation.agents.proactive_monitor import ProactiveMonitorAgent

        monitor = container.resolve(ProactiveMonitorAgent)
        result = await monitor.scan_patient(patient_id)

        if result.insights:
            await _send_notification(patient_id, result.insights, monitor)

        return TaskResult(
            success=True,
            data={
                "patient_id": patient_id,
                "insight_count": len(result.insights),
                "alert_count": result.alert_count,
                "scan_duration_ms": result.scan_duration_ms,
            },
        )
    except Exception as e:
        logger.error(f"Proactive scan failed for {patient_id}: {e}")
        return TaskResult(success=False, error=str(e), data={"patient_id": patient_id})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _filter_by_scan_window(
    patient_ids: list[str],
    timezones: dict[str, str],
) -> tuple[list[str], int]:
    """Filter patients to those within their local scan window (7 AM - 10 PM)."""
    eligible: list[str] = []
    skipped = 0
    for pid in patient_ids:
        if is_within_scan_window(timezones.get(pid, DEFAULT_TIMEZONE)):
            eligible.append(pid)
        else:
            skipped += 1
    return eligible, skipped


async def _send_notification(
    patient_id: str,
    insights: list,
    monitor: Any,
) -> None:
    """Send ONE push notification — the most severe insight — and record it."""
    try:
        from lib.services.fcm_service import FCMService

        top = max(insights, key=lambda i: SEVERITY_RANK.get(i.severity.value, 0))
        is_urgent = top.severity.value in ("warning", "alert")

        await FCMService().send_fcm_notification_to_user_devices(
            user_id=patient_id,
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
        await monitor.record_insight(patient_id, top)
    except Exception as e:
        logger.warning(f"Failed to send notification for {patient_id}: {e}")


async def _get_active_patient_ids() -> list[str]:
    """Fetch patient IDs with active devices in the last 7 days.

    Uses UserDevice table instead of meal_reports — catches patients
    with CGM sync, vitals, or any app activity (not just meal logs).
    Also filters out patients with less than _MIN_HISTORY_DAYS of history.
    """
    try:
        from lib.dependencies.database import postgres_store
        from sqlalchemy import select, and_
        from lib.models.user_device import UserDevice

        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        min_signup = datetime.now(timezone.utc) - timedelta(days=_MIN_HISTORY_DAYS)

        async with postgres_store.get_session() as session:
            stmt = (
                select(UserDevice.user_id)
                .where(and_(
                    UserDevice.profile_type == "patient",
                    UserDevice.is_active == True,  # noqa: E712
                    UserDevice.last_active_at >= cutoff,
                    UserDevice.created_at <= min_signup,
                ))
                .distinct()
            )
            result = await session.execute(stmt)
            return [str(row[0]) for row in result.fetchall()]
    except Exception as e:
        logger.warning(f"Failed to fetch active patients: {e}")
        return []
