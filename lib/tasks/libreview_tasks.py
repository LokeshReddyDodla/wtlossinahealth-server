from datetime import datetime, timedelta
import logging

from celery import shared_task

from lib.models.patient import Patient as PatientModel
from lib.services.libreview_service import LibreViewService

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
async def sync_all_libreview(self):
    try:
        result = await _sync_all_libreview_async()
        return result

    except Exception as exc:
        logger.error(f"Failed to sync LibreView data: {str(exc)}")
        self.retry(exc=exc, countdown=60)


async def _sync_all_libreview_async():
    from lib.dependencies.service_dependencies import get_libreview_service

    libreview_service = get_libreview_service()
    patients = await libreview_service.get_patients_with_libreview()  # type: ignore

    # Process each patient
    results = []
    for patient in patients:
        try:
            result = await _sync_patient_libreview(
                patient,
                libreview_service,
            )
            results.append(result)
        except Exception as e:
            logger.error(
                f"Failed to sync patient {patient.patient_id}: {str(e)}"
            )
            results.append(
                {
                    "patient_id": str(patient.patient_id),
                    "status": "error",
                    "error": str(e),
                }
            )

    return {
        "status": "completed",
        "results": results,
        "total_patients": len(patients),
        "successful_syncs": len(
            [r for r in results if r.get("status") == "success"]
        ),
    }


async def _sync_patient_libreview(
    patient: PatientModel, libreview_service: LibreViewService
) -> dict:
    libreview = patient.connected_apps.libreview
    patient_id = str(patient.patient_id)

    # Check if sync is needed (optional)
    if libreview.last_sync_timestamp and (
        datetime.utcnow() - libreview.last_sync_timestamp
    ) < timedelta(hours=2):
        return {
            "patient_id": patient_id,
            "status": "skipped",
            "reason": "Sync was performed recently",
        }

    # Perform the actual sync
    sync_result = await libreview_service.sync_libreview(
        patient_id=patient_id, user_id=patient_id
    )
    logger.info(sync_result)

    return {
        "patient_id": patient_id,
        "status": "success",
        "data": sync_result,
    }
