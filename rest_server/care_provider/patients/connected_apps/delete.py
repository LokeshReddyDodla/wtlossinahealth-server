from datetime import datetime, timedelta
import json
from fastapi import Depends, HTTPException, Query, Request, status

from lib.dependencies.auth.base import get_current_user
from lib.dependencies.auth.care_provider_auth import get_current_care_provider
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
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse
from lib.models.care_provider import CareProvider as CareProviderModel

from .router import router


@router.delete(
    "/libreview",
    response_model=SuccessResponse,
)
async def disconnect_libreview(
    patient_id: str,
    patient_connected_app_service: PatientConnectedAppService = Depends(
        get_patient_connected_app_service
    ),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.UPDATE,
            CareProviderFeature.PATIENTS,
        )
    ),
):
    try:
        await patient_connected_app_service.remove_libreview(
            patient_id=patient_id,
        )

        return SuccessResponse(
            message="LibreView unlinked successfully.",
            data=None,
        )
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )


@router.delete(
    "/sinocare",
    response_model=SuccessResponse,
)
async def disconnect_sinocare(
    patient_id: str,
    patient_connected_app_service: PatientConnectedAppService = Depends(
        get_patient_connected_app_service
    ),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.UPDATE,
            CareProviderFeature.PATIENTS,
        )
    ),
):
    try:
        await patient_connected_app_service.remove_sinocare(
            patient_id=patient_id,
        )

        return SuccessResponse(
            message="Sinocare unlinked successfully.",
            data=None,
        )
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
