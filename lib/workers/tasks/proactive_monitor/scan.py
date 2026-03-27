"""
Proactive Monitor Worker Task — runs patient health scans on a cron schedule.

Designed to be registered as an arq cron job. Fetches active patient IDs
and runs the ProactiveMonitorAgent.scan_batch() pipeline.

Includes timezone-aware scheduling: patients are only scanned between 7 AM
and 10 PM in their local timezone (defaults to Asia/Kolkata).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from loguru import logger

from lib.ai_foundation.agents.proactive_monitor.scheduling import (
    DEFAULT_TIMEZONE,
    is_within_scan_window,
)
from lib.workers.tasks.base import TaskResult, task_with_logging


@task_with_logging
async def run_proactive_scan(
    ctx: Dict[str, Any],
    patient_ids: Optional[list[str]] = None,
) -> TaskResult:
    """Scan patients for proactive health insights.

    If patient_ids is None, scans all active patients (last 7 days of data).
    Patients outside their local scan window (7 AM - 10 PM) are skipped.
    """
    try:
        from lib.core.container import container
        from lib.ai_foundation.agents.proactive_monitor import ProactiveMonitorAgent

        monitor: ProactiveMonitorAgent = container.resolve(ProactiveMonitorAgent)

        # If no patient_ids provided, fetch active patients
        if not patient_ids:
            patient_ids = await _get_active_patient_ids()

        if not patient_ids:
            return TaskResult(success=True, data={"message": "No active patients to scan"})

        # Batch-resolve names + timezones (cached 5 min via PatientNameResolver)
        from lib.ai_foundation.agents.health_query.patient_resolver import PatientNameResolver
        resolver: PatientNameResolver = container.resolve(PatientNameResolver)
        all_names = await resolver.resolve_names(patient_ids)
        all_timezones = await resolver.resolve_timezones(patient_ids)

        # Filter to patients within their scan window
        eligible_ids = []
        skipped = 0
        for pid in patient_ids:
            tz = all_timezones.get(pid, DEFAULT_TIMEZONE)
            if is_within_scan_window(tz):
                eligible_ids.append(pid)
            else:
                skipped += 1

        if skipped:
            logger.info(
                "Timezone filter: %d/%d patients outside scan window, skipping",
                skipped, len(patient_ids),
            )

        if not eligible_ids:
            return TaskResult(
                success=True,
                data={
                    "message": "All patients outside scan window",
                    "total": len(patient_ids),
                    "skipped_timezone": skipped,
                },
            )

        # Filter metadata to eligible patients only
        patient_names = {pid: all_names[pid] for pid in eligible_ids if pid in all_names}
        patient_timezones = {pid: all_timezones.get(pid, DEFAULT_TIMEZONE) for pid in eligible_ids}

        batch = await monitor.scan_batch(
            eligible_ids,
            patient_names=patient_names,
            patient_timezones=patient_timezones,
        )

        # Send notifications
        await _send_notifications(batch)

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
    ctx: Dict[str, Any],
    patient_id: str,
) -> TaskResult:
    """Scan a single patient. Useful for event-triggered scans."""
    try:
        from lib.core.container import container
        from lib.ai_foundation.agents.proactive_monitor import ProactiveMonitorAgent

        monitor: ProactiveMonitorAgent = container.resolve(ProactiveMonitorAgent)
        result = await monitor.scan_patient(patient_id)

        if result.insights:
            await _send_patient_notifications(patient_id, result.insights)

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


async def _get_active_patient_ids() -> list[str]:
    """Fetch patient IDs who have logged data in the last 7 days."""
    try:
        from lib.core.container import container
        from lib.core.mongo_store import MongoStore

        mongo: MongoStore = container.resolve(MongoStore)
        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

        # Check meal_reports for recent activity (most commonly logged)
        collection = mongo.get_collection("meal_reports")
        patient_ids = await collection.distinct(
            "patient_id",
            {"date": {"$gte": week_ago[:10]}},
        )
        return list(set(patient_ids)) if patient_ids else []
    except Exception as e:
        logger.warning(f"Failed to fetch active patients: {e}")
        return []


async def _send_notifications(batch) -> None:
    """Send push notifications for all insights in a batch."""
    for result in batch.results:
        if result.insights:
            await _send_patient_notifications(result.patient_id, result.insights)


async def _send_patient_notifications(patient_id: str, insights: list) -> None:
    """Send ONE push notification per patient — the most severe insight only."""
    try:
        from lib.core.container import container
        from lib.ai_foundation.agents.proactive_monitor import ProactiveMonitorAgent
        from lib.services.fcm_service import FCMService

        fcm = FCMService()
        from lib.ai_foundation.agents.proactive_monitor.contracts import SEVERITY_RANK
        notifiable = list(insights)

        if notifiable:
            top = max(notifiable, key=lambda i: SEVERITY_RANK.get(i.severity.value, 0))
            is_urgent = top.severity.value in ("warning", "alert")
            await fcm.send_fcm_notification_to_user_devices(
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
                    "suggested_query": top.suggested_query or "",
                    "total_insights": str(len(insights)),
                },
            )
            # Record only the insight we actually sent
            monitor: ProactiveMonitorAgent = container.resolve(ProactiveMonitorAgent)
            await monitor.record_insight(patient_id, top)
    except Exception as e:
        logger.warning(f"Failed to send notifications for {patient_id}: {e}")
