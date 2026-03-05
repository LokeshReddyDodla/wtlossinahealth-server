"""LibreView Sync Worker Task."""

from datetime import datetime
from typing import Any, Dict

from loguru import logger
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from lib.dependencies.database import postgres_store
from lib.models.patient_connected_app import PatientConnectedApp
from lib.services.libreview_client import LibreViewClient
from lib.workers.tasks.base import TaskResult, task_with_logging


@task_with_logging
async def sync_patient_libreview(
    ctx: Dict[str, Any],
    patient_id: str,
) -> TaskResult:
    """Sync LibreView CGM data for a patient."""
    job_id = ctx.get("job_id", "unknown")

    logger.info(
        f"[sync_patient_libreview] Starting sync for patient {patient_id} (job: {job_id})"
    )

    try:
        # Step 1: Get LibreView ID from database
        async with postgres_store.get_session() as session:
            result = await session.execute(
                select(PatientConnectedApp)
                .where(PatientConnectedApp.patient_id == patient_id)
                .options(selectinload(PatientConnectedApp.libreview))
            )
            connected_app = result.scalars().first()

            if not connected_app:
                error_msg = f"No connected apps found for patient {patient_id}"
                logger.error(f"[sync_patient_libreview] {error_msg}")
                return TaskResult(success=False, error=error_msg)

            if not connected_app.libreview:
                error_msg = f"LibreView not connected for patient {patient_id}"
                logger.error(f"[sync_patient_libreview] {error_msg}")
                return TaskResult(success=False, error=error_msg)

            libreview_id = connected_app.libreview.libreview_id
            logger.info(f"[sync_patient_libreview] Found LibreView ID: {libreview_id}")

        # Step 2-5: Sync data from LibreView (solve captcha, request, poll, download)
        client = LibreViewClient()
        csv_data = await client.sync_patient_data(libreview_id)

        logger.info(
            f"[sync_patient_libreview] Downloaded {len(csv_data)} bytes of CSV data"
        )

        # Step 6: Upload to ClickHouse via existing service
        from lib.dependencies.service_dependencies import get_cgm_service

        cgm_service = get_cgm_service()
        await cgm_service.parse_and_upload_libreview_raw_csv_data(
            patient_id=patient_id,
            file_contents=csv_data,
        )  # type: ignore

        logger.info(
            f"[sync_patient_libreview] Successfully synced data for patient {patient_id}"
        )

        return TaskResult(
            success=True,
            data={
                "patient_id": patient_id,
                "libreview_id": libreview_id,
                "synced_at": datetime.now().isoformat(),
                "bytes_downloaded": len(csv_data),
            },
        )

    except Exception as e:
        error_msg = f"LibreView sync failed for patient {patient_id}: {str(e)}"
        logger.error(f"[sync_patient_libreview] {error_msg}", exc_info=True)
        return TaskResult(success=False, error=error_msg)


@task_with_logging
async def sync_all_patients_libreview(ctx: Dict[str, Any]) -> TaskResult:
    """
    Scheduled task to sync LibreView data for all patients with LibreView connected.
    Respects 3-hour cooldown per patient. Skips patients already in sync queue.
    """
    logger.info(
        "[sync_all_patients_libreview] Starting scheduled LibreView sync for all patients"
    )

    stats = {
        "total_patients": 0,
        "synced": 0,
        "in_queue": 0,
        "cooldown_skipped": 0,
        "paused_skipped": 0,
        "inactive_skipped": 0,
        "errors": 0,
        "error_details": [],
    }

    try:
        # Get service from container
        from lib.dependencies.service_dependencies import get_libreview_service

        libreview_service = get_libreview_service()

        # Get patients eligible for sync (active, not paused, with recent activity)
        async with postgres_store.get_session() as session:
            patients = await libreview_service.get_patients_eligible_for_sync(
                postgres_session=session
            )  # type: ignore

        stats["total_patients"] = len(patients)
        logger.info(
            f"[sync_all_patients_libreview] Found {len(patients)} patients eligible for sync"
        )

        # Sync each patient
        for patient in patients:
            patient_id = str(patient.patient_id)
            logger.info(
                f"[sync_all_patients_libreview] Processing patient {patient_id}"
            )

            try:
                result = await libreview_service.sync_libreview(
                    patient_id=patient_id,
                    force=False,  # Respect cooldown
                )

                # Defensive check
                if not isinstance(result, dict) or "status" not in result:
                    logger.warning(
                        f"[sync_all_patients_libreview] Unexpected response for patient {patient_id}: {result}"
                    )
                    stats["synced"] += 1
                    stats["error_details"].append(
                        f"Invalid response for patient {patient_id}: {result}"
                    )
                    continue

                status = result["status"]

                if status == "in_queue":
                    stats["in_queue"] += 1
                    logger.info(
                        f"[sync_all_patients_libreview] Patient {patient_id} already in queue, skipping"
                    )
                elif status == "cooldown":
                    stats["cooldown_skipped"] += 1
                    logger.info(
                        f"[sync_all_patients_libreview] Patient {patient_id} on cooldown, skipping"
                    )
                elif status == "paused":
                    stats["paused_skipped"] += 1
                    logger.info(
                        f"[sync_all_patients_libreview] Patient {patient_id} sync is paused, skipping"
                    )
                elif status == "queued":
                    stats["synced"] += 1
                    logger.info(
                        f"[sync_all_patients_libreview] Successfully enqueued sync for patient {patient_id}"
                    )
                else:
                    logger.warning(
                        f"[sync_all_patients_libreview] Unknown status '{status}' for patient {patient_id}"
                    )
                    stats["synced"] += 1

            except Exception as e:
                stats["errors"] += 1
                error_msg = f"Failed to sync patient {patient_id}: {str(e)}"
                stats["error_details"].append(error_msg)
                logger.error(
                    f"[sync_all_patients_libreview] {error_msg}", exc_info=True
                )

        # Log summary
        logger.info(
            f"[sync_all_patients_libreview] Completed scheduled sync. "
            f"Eligible: {stats['synced']}, In Queue: {stats['in_queue']}, "
            f"Cooldown: {stats['cooldown_skipped']}, Paused: {stats['paused_skipped']}, "
            f"Errors: {stats['errors']}"
        )

        return TaskResult(
            success=True,
            data=stats,
        )

    except Exception as e:
        error_msg = f"LibreView scheduled sync failed: {str(e)}"
        logger.error(f"[sync_all_patients_libreview] {error_msg}", exc_info=True)
        return TaskResult(success=False, error=error_msg)
