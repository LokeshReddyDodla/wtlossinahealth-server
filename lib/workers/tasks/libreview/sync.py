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
        )

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
