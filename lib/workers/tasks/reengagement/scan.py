"""Re-engagement scan — nudge inactive patients back to the app.

Runs twice weekly (Tue + Fri). Queries patients with no device activity
in 7-30 days, assigns a tier (gentle/nudge/last_call), and sends a
templated push notification. Caps at 3 attempts per patient.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from lib.workers.tasks.base import TaskResult, task_with_logging

logger = logging.getLogger(__name__)

_MAX_ATTEMPTS = 3


@task_with_logging
async def run_reengagement_scan(ctx: dict[str, Any]) -> TaskResult:
    """Find inactive patients and send tiered re-engagement notifications."""
    try:
        from lib.core.container import container
        from lib.ai_foundation.agents.core.patient_resolver import PatientNameResolver
        from lib.ai_foundation.agents.proactive_monitor.insight_tracker import InsightTracker
        from lib.ai_foundation.agents.proactive_monitor.scheduling import (
            DEFAULT_TIMEZONE,
            is_within_scan_window,
        )
        from lib.services.fcm_service import FCMService

        from .templates import get_message, get_tier

        resolver = container.resolve(PatientNameResolver)
        tracker = container.resolve(InsightTracker)
        fcm = FCMService()

        # 1. Query inactive patients (7-30 days, with FCM token)
        inactive = await _get_inactive_patient_ids()
        if not inactive:
            return TaskResult(success=True, data={"message": "No inactive patients found"})

        patient_ids = [pid for pid, _ in inactive]
        last_active_map = {pid: ts for pid, ts in inactive}

        # 2. Batch-resolve names + timezones
        all_names = await resolver.resolve_names(patient_ids)
        all_timezones = await resolver.resolve_timezones(patient_ids)

        # 3. Filter by scan window (7am-10pm local)
        eligible_ids: list[str] = []
        skipped_tz = 0
        for pid in patient_ids:
            tz = all_timezones.get(pid, DEFAULT_TIMEZONE)
            if is_within_scan_window(tz):
                eligible_ids.append(pid)
            else:
                skipped_tz += 1

        if not eligible_ids:
            return TaskResult(success=True, data={
                "message": "All inactive patients outside scan window",
                "total_inactive": len(patient_ids),
                "skipped_timezone": skipped_tz,
            })

        # 4. Check attempt counts (batch) — skip patients already at cap
        attempt_counts = await _get_attempt_counts(tracker, eligible_ids)
        uncapped: list[str] = []
        skipped_capped = 0
        for pid in eligible_ids:
            if attempt_counts.get(pid, 0) >= _MAX_ATTEMPTS:
                skipped_capped += 1
            else:
                uncapped.append(pid)

        # 5. Send notifications
        sent = 0
        errors = 0
        for pid in uncapped:
            try:
                # Dedup check (24h window)
                should_send, _, _ = await tracker.should_send(pid, "engagement_drop")
                if not should_send:
                    continue

                last_active = last_active_map[pid]
                now = datetime.now(timezone.utc)
                if last_active.tzinfo is None:
                    last_active = last_active.replace(tzinfo=timezone.utc)
                days_inactive = (now - last_active).days

                tier = get_tier(days_inactive)
                if tier is None:
                    continue

                # Extract first name
                full_name = all_names.get(pid) or ""
                first_name = full_name.split()[0] if full_name and not full_name.startswith("Patient") else "there"

                attempt = attempt_counts.get(pid, 0) + 1
                title, body = get_message(tier, first_name, days_inactive, attempt)

                from lib.services.notification_budget import can_send, record_sent
                if not can_send(pid, "re_engagement"):
                    continue

                await fcm.send_fcm_notification_to_user_devices(
                    user_id=pid,
                    title=title,
                    body=body,
                    channel_key="reminders",
                    group_key="reminder_group",
                    data={
                        "type": "reengagement",
                        "tier": tier.value,
                        "days_inactive": str(days_inactive),
                    },
                )
                record_sent(pid)

                await tracker.record(
                    pid,
                    "engagement_drop",
                    "info",
                    body,
                    title=title,
                )
                sent += 1

            except Exception as exc:
                logger.warning("Re-engagement failed for %s: %s", pid, exc)
                errors += 1

        return TaskResult(success=True, data={
            "total_inactive": len(patient_ids),
            "eligible": len(uncapped),
            "sent": sent,
            "skipped_timezone": skipped_tz,
            "skipped_capped": skipped_capped,
            "errors": errors,
        })

    except Exception as exc:
        logger.error("Re-engagement scan failed: %s", exc)
        return TaskResult(success=False, error=str(exc))


async def _get_inactive_patient_ids() -> list[tuple[str, datetime]]:
    """Fetch patients with no device activity in 7-30 days.

    Returns (user_id, max_last_active_at) tuples. Uses the most recent
    last_active_at across all of a patient's devices. Requires at least
    one active device with a valid FCM token.
    """
    from lib.dependencies.database import postgres_store
    from sqlalchemy import select, and_, func
    from lib.models.user_device import UserDevice

    now = datetime.utcnow()  # naive UTC — matches TIMESTAMP WITHOUT TIME ZONE
    cutoff_min = now - timedelta(days=30)
    cutoff_max = now - timedelta(days=7)

    async with postgres_store.get_session() as session:
        stmt = (
            select(
                UserDevice.user_id,
                func.max(UserDevice.last_active_at).label("last_active"),
            )
            .where(and_(
                UserDevice.profile_type == "patient",
                UserDevice.is_active == True,  # noqa: E712
                UserDevice.fcm_token.isnot(None),
            ))
            .group_by(UserDevice.user_id)
            .having(and_(
                func.max(UserDevice.last_active_at) >= cutoff_min,
                func.max(UserDevice.last_active_at) <= cutoff_max,
            ))
        )
        result = await session.execute(stmt)
        return [(str(row[0]), row[1]) for row in result.fetchall()]


async def _get_attempt_counts(
    tracker: Any,
    patient_ids: list[str],
) -> dict[str, int]:
    """Count engagement_drop records per patient in the last 30 days.

    Uses a single MongoDB aggregation for efficiency.
    """
    since = datetime.now(timezone.utc) - timedelta(days=30)

    pipeline = [
        {"$match": {
            "patient_id": {"$in": patient_ids},
            "category": "engagement_drop",
            "created_at": {"$gte": since},
        }},
        {"$group": {"_id": "$patient_id", "count": {"$sum": 1}}},
    ]

    counts: dict[str, int] = {}
    async for doc in tracker._collection.aggregate(pipeline):
        counts[doc["_id"]] = doc["count"]
    return counts
