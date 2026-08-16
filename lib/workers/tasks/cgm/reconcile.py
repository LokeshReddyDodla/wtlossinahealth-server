"""Reconcile CGM daily reports + vectors for live-synced patients.

Live-streaming ingestion (`CGMUploadService.write_readings`, e.g. the
LibreLinkUp follower cron) lands glucose in ClickHouse but — unlike the CSV
path — never triggers report/vector generation. So live-synced CGM is invisible
to the AI layer, which reads Qdrant. This periodic sweep converges every source:
any path that advances `last_cgm_reading_at` is covered, with no per-writer
wiring to forget.

For each patient whose newest reading is ahead of their newest daily report, it
enqueues the existing `process_cgm_upload` chain (report -> vector) for the gap.
That chain is idempotent, so this is safe to run alongside the immediate CSV
trigger and to re-run: overlapping work is skipped by the existing filters.

The first run for a patient who has readings but no daily reports doubles as the
backfill — bounded to the recent window so a months-long history isn't rebuilt.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

from loguru import logger
from sqlalchemy.future import select

from lib.dependencies.database import postgres_store
from lib.models.patient_connected_app import (
    PatientConnectedApp,
    PatientLibreView,
    PatientSinocare,
)
from lib.workers.tasks.base import TaskResult, task_with_logging
from lib.workers.tasks.cgm.enqueue import enqueue_cgm_report_generation_async

# Only consider patients who synced within this window; caps first-connect
# backfill so a long history isn't rebuilt in one sweep.
_RECENT_DAYS = 7
_FIRST_CONNECT_CAP_DAYS = 30

# Sources that track a CGM reading frontier. A new CGM source with its own
# last_cgm_reading_at is added here — the one place the sweep needs to know.
_FRONTIER_MODELS = (PatientLibreView, PatientSinocare)


def _naive_utc_now() -> datetime:
    # last_cgm_reading_at is a naive TIMESTAMP WITHOUT TIME ZONE; compare naive.
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _recent_reading_frontiers(cutoff: datetime) -> dict[str, datetime]:
    """{patient_id: newest last_cgm_reading_at} across sources, since cutoff."""
    frontiers: dict[str, datetime] = {}
    async with postgres_store.get_session() as session:
        for model in _FRONTIER_MODELS:
            rows = await session.execute(
                select(PatientConnectedApp.patient_id, model.last_cgm_reading_at)
                .join(model, model.connected_app_id == PatientConnectedApp.id)
                .where(model.last_cgm_reading_at.is_not(None))
                .where(model.last_cgm_reading_at >= cutoff)
            )
            for patient_id, reading_at in rows.all():
                pid = str(patient_id)
                if pid not in frontiers or reading_at > frontiers[pid]:
                    frontiers[pid] = reading_at
    return frontiers


@task_with_logging
async def reconcile_cgm_vectors(ctx: dict[str, Any]) -> TaskResult:
    """Enqueue report+vector generation for patients whose reports lag readings."""
    from lib.dependencies.service_dependencies import get_cgm_report_service

    cutoff = _naive_utc_now() - timedelta(days=_RECENT_DAYS)
    frontiers = await _recent_reading_frontiers(cutoff)
    if not frontiers:
        return TaskResult(success=True, data={"candidates": 0, "enqueued": 0})

    report_ends = await get_cgm_report_service().latest_daily_report_ends(
        list(frontiers)
    )

    enqueued = 0
    for patient_id, reading_at in frontiers.items():
        report_end = report_ends.get(patient_id)
        if report_end is None:
            # No daily reports yet — first-connect backfill, capped.
            start = reading_at - timedelta(days=_FIRST_CONNECT_CAP_DAYS)
        elif reading_at.date() > report_end.date():
            # New day(s) of readings since the last report; re-anchor to the
            # last report's day so the open day is refreshed and new days added.
            start = datetime(report_end.year, report_end.month, report_end.day)
        else:
            continue  # reports already cover the newest reading day

        await enqueue_cgm_report_generation_async(
            patient_id,
            [{
                "start": start.isoformat(),
                "end": reading_at.isoformat(),
                "sensor_status": "OPEN",
            }],
        )
        enqueued += 1

    logger.info(
        f"[reconcile_cgm_vectors] {enqueued}/{len(frontiers)} patients enqueued"
    )
    return TaskResult(
        success=True, data={"candidates": len(frontiers), "enqueued": enqueued}
    )
