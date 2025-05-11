from datetime import datetime, timedelta
import json
from fastapi import Depends, HTTPException, Query, Request, status

from lib.dependencies.auth.base import get_current_user
from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.service_dependencies import (
    get_libreview_sync_queue,
    get_patient_connected_app_service,
)
from lib.models.patient import Patient
from lib.schemas.patient_connected_app import (
    PatientLibreView as PatientLibreViewSchema,
)
from lib.schemas.patient_connected_app import PatientLibreViewCreate
from lib.services.patient_connected_app_service import (
    PatientConnectedAppService,
)
from lib.services.sqs_service import SQSService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.post(
    "/libreview",
    response_model=SuccessResponse,
)
async def upsert_libreview(
    request: Request,
    libreview_data: PatientLibreViewCreate,
    patient_connected_app_service: PatientConnectedAppService = Depends(
        get_patient_connected_app_service
    ),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        libreview = (
            await patient_connected_app_service.add_or_update_libreview(
                libreview_data=libreview_data,
                patient_id=str(current_patient.patient_id),
            )
        )

        libreview = PatientLibreViewSchema.model_validate(libreview)

        return SuccessResponse(
            message="LibreView data updated successfully.",
            data=libreview,
        )
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )


SYNC_INTERVAL_SECONDS = 2 * 60 * 60  # 2 hours
REDIS_SYNC_TTL_SECONDS = 30 * 60  # Optional: Keep Redis lock for 30 min


@router.post(
    "/libreview/sync",
    response_model=SuccessResponse,
)
async def sync_libreview(
    request: Request,
    patient_id: str = Query(...),
    patient_connected_app_service: PatientConnectedAppService = Depends(
        get_patient_connected_app_service
    ),
    libreview_sync_queue: SQSService = Depends(get_libreview_sync_queue),
    current_user=Depends(get_current_user),
):
    try:
        libreview_sync_store = request.state.context.libreview_sync_store
        user_id, role = current_user

        connected_apps = (
            await patient_connected_app_service.get_connected_apps_for_patient(
                patient_id=patient_id,
            )
        )
        if not connected_apps.libreview:
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="LibreView not connected for this patient.",
            )

        libreview = PatientLibreViewSchema.model_validate(
            connected_apps.libreview
        )
        last_sync = connected_apps.libreview.last_sync_timestamp

        # Step 1: Check sync interval
        if last_sync and (datetime.utcnow() - last_sync) < timedelta(
            seconds=SYNC_INTERVAL_SECONDS
        ):
            raise_http_exception(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                message="Sync allowed only once every 2 hours.",
            )

        # Step 2: Redis key to prevent duplicate SQS messages
        redis_key = f"{libreview.libreview_id}:{patient_id}"
        if libreview_sync_store.get_key(redis_key):
            return SuccessResponse(
                message="Sync already in progress (in queue).",
                data={"status": "already_queued"},
            )

        # Step 4: Prepare payload and send to SQS
        payload = {
            "patient_id": patient_id,
            "libreview_id": libreview.libreview_id,
            "requested_by": str(user_id),
            "timestamp": int(datetime.utcnow().timestamp() * 1000),
        }

        libreview_sync_queue.send_message(
            deduplication_id=redis_key,
            payload=payload,
        )

        # Step 5: Save payload in Redis
        libreview_sync_store.set_key(
            redis_key, json.dumps(payload), expire=REDIS_SYNC_TTL_SECONDS
        )

        return SuccessResponse(
            message="Sync request accepted and added to queue.",
            data={"status": "queued"},
        )
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
