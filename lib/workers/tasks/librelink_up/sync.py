"""LibreLinkUp follower-API sync task.

Single ARQ task driven by a 5-min cron. One login (cached), one
`/llu/connections` call, then one `/graph` call per matched patient. Writes
normalized rows to ClickHouse via `CGMUploadService.write_readings`.
"""

from typing import Any, Dict

import httpx
from decouple import config
from loguru import logger
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from lib.dependencies.database import postgres_store
from lib.models.patient_connected_app import PatientConnectedApp, PatientLibreView
from lib.services.librelink_up_client import LibreLinkUpClient
from lib.workers.tasks.base import TaskResult, task_with_logging


def _is_enabled() -> bool:
    raw = config("LIBRELINKUP_ENABLED", default="true")
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


@task_with_logging
async def sync_all_patients_librelink_up(ctx: Dict[str, Any]) -> TaskResult:
    """Pull rolling-12h glucose for every llu-enabled patient."""
    if not _is_enabled():
        logger.info(
            "[sync_all_patients_librelink_up] disabled via LIBRELINKUP_ENABLED"
        )
        return TaskResult(success=True, data={"status": "disabled"})

    stats = {
        "connections": 0,
        "matched": 0,
        "synced": 0,
        "rows_written": 0,
        "skipped": 0,
        "errors": 0,
        "error_details": [],
    }

    try:
        # Build libreview_id → (patient_id, libreview_row) map for enabled patients.
        async with postgres_store.get_session() as session:
            result = await session.execute(
                select(PatientConnectedApp)
                .options(selectinload(PatientConnectedApp.libreview))
                .join(PatientLibreView)
                .where(PatientLibreView.llu_enabled.is_(True))
            )
            connected_apps = result.scalars().all()

        eligible: dict[str, str] = {}
        for app in connected_apps:
            if not app.libreview or not app.libreview.libreview_id:
                continue
            eligible[app.libreview.libreview_id.strip()] = str(app.patient_id)

        if not eligible:
            logger.info("[sync_all_patients_librelink_up] no eligible patients")
            return TaskResult(success=True, data=stats)

        from lib.dependencies.service_dependencies import get_cgm_service

        cgm_service = get_cgm_service()

        async with LibreLinkUpClient() as client:
            connections = await client.connections()
            stats["connections"] = len(connections)

            for conn in connections:
                llu_pid = conn.get("patientId")
                if not llu_pid or llu_pid not in eligible:
                    stats["skipped"] += 1
                    continue

                internal_pid = eligible[llu_pid]
                stats["matched"] += 1

                try:
                    rows = await client.fetch_readings_for_connection(
                        llu_pid, internal_pid
                    )
                    if not rows:
                        continue
                    written = await cgm_service.write_readings(
                        patient_id=internal_pid,
                        rows=rows,
                        source="librelinkup",
                    )  # type: ignore
                    stats["synced"] += 1
                    stats["rows_written"] += written
                except httpx.HTTPStatusError as e:
                    stats["errors"] += 1
                    msg = (
                        f"patient {internal_pid} (llu={llu_pid}) "
                        f"HTTP {e.response.status_code}"
                    )
                    stats["error_details"].append(msg)
                    logger.warning("[sync_all_patients_librelink_up] {}", msg)
                except Exception as e:
                    stats["errors"] += 1
                    msg = f"patient {internal_pid}: {e}"
                    stats["error_details"].append(msg)
                    logger.exception(
                        "[sync_all_patients_librelink_up] {}", msg
                    )

        logger.info(
            "[sync_all_patients_librelink_up] connections={} matched={} "
            "synced={} rows={} errors={}",
            stats["connections"],
            stats["matched"],
            stats["synced"],
            stats["rows_written"],
            stats["errors"],
        )
        return TaskResult(success=True, data=stats)

    except Exception as e:
        logger.exception("[sync_all_patients_librelink_up] fatal: {}", e)
        return TaskResult(success=False, error=str(e))
