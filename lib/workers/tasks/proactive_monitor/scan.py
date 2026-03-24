"""
Proactive Monitor Worker Task — runs patient health scans on a cron schedule.

Designed to be registered as an arq cron job. Fetches active patient IDs
and runs the ProactiveMonitorAgent.scan_batch() pipeline.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from loguru import logger

from lib.workers.tasks.base import TaskResult, task_with_logging


@task_with_logging
async def run_proactive_scan(
    ctx: Dict[str, Any],
    patient_ids: Optional[list[str]] = None,
) -> TaskResult:
    """Scan patients for proactive health insights.

    If patient_ids is None, scans all active patients (last 7 days of data).
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

        batch = await monitor.scan_batch(patient_ids)

        # Send notifications for insights with severity >= attention
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


async def _get_active_patient_ids() -> list[str]:
    """Fetch patient IDs who have logged data in the last 7 days."""
    try:
        from lib.core.container import container
        from lib.core.mongo_store import MongoStore
        from datetime import datetime, timedelta, timezone

        mongo: MongoStore = container.resolve(MongoStore)
        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

        # Check meal_reports for recent activity (most commonly logged)
        collection = mongo.get_collection("meal_reports")
        cursor = collection.distinct(
            "patient_id",
            {"date": {"$gte": week_ago[:10]}},
        )
        patient_ids = await cursor if hasattr(cursor, '__await__') else cursor
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
    """Send push notifications for a patient's insights."""
    try:
        from lib.services.fcm_service import FCMService

        fcm = FCMService()
        for insight in insights:
            # Only send push for attention+ severity
            if insight.severity.value in ("attention", "warning", "alert"):
                await fcm.send_fcm_notification_to_user_devices(
                    user_id=patient_id,
                    title=insight.title,
                    body=insight.body,
                    channel_key="health_insights",
                    group_key="health_insights_group",
                    data={
                        "type": "proactive_insight",
                        "insight_id": insight.insight_id,
                        "category": insight.category.value,
                        "severity": insight.severity.value,
                        "suggested_query": insight.suggested_query or "",
                    },
                )
    except Exception as e:
        logger.warning(f"Failed to send notifications for {patient_id}: {e}")
