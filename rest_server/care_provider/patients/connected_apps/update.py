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


@router.post(
    "/libreview",
    response_model=SuccessResponse,
)
async def upsert_libreview(
    patient_id: str,
    libreview_data: PatientLibreViewCreate,
    patient_connected_app_service: PatientConnectedAppService = Depends(
        get_patient_connected_app_service
    ),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.READ, CareProviderFeature.REPORTS
        )
    ),
):
    try:
        libreview = (
            await patient_connected_app_service.add_or_update_libreview(
                libreview_data=libreview_data,
                patient_id=patient_id,
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
