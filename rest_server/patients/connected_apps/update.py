from datetime import datetime, timedelta
import json
from typing import Union

from fastapi import Depends, HTTPException, Query, Request, status

from lib.dependencies.auth.base import get_current_user
from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.service_dependencies import (
    get_libreview_service,
    get_libreview_sync_queue,
    get_patient_connected_app_service,
)
from lib.models.patient import Patient
from lib.schemas.patient_connected_app import (
    PatientLibreView as PatientLibreViewSchema,
)
from lib.schemas.patient_connected_app import PatientLibreViewCreate
from lib.services.libreview_service import LibreViewService
from lib.services.patient_connected_app_service import (
    PatientConnectedAppService,
)
from lib.services.sqs_service import SQSService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import InQueueResponse, SuccessResponse

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
                libreview_id=libreview_data.libreview_id,
                patient_id=str(current_patient.patient_id),
            )  # type: ignore
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


@router.post(
    "/libreview/sync",
    response_model=Union[SuccessResponse, InQueueResponse],
)
async def sync_libreview(
    request: Request,
    patient_id: str = Query(...),
    force: bool = Query(default=False),
    libreview_service: LibreViewService = Depends(get_libreview_service),
    current_user=Depends(get_current_user),
):
    try:
        result = await libreview_service.sync_libreview(patient_id, force=force)

        if result.get("status") == "in_queue":
            return InQueueResponse(**result)

        return SuccessResponse(**result)
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
