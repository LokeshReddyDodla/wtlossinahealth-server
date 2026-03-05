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
from lib.schemas.patient_connected_app import (
    PatientSinocare as PatientSinocareSchema,
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
    "/libreview/connect",
    response_model=SuccessResponse,
)
async def connect_libreview(
    patient_id: str,
    libreview_id: str,
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
                libreview_id=libreview_id,
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


@router.post(
    "/sinocare/connect",
    response_model=SuccessResponse,
)
async def connect_sinocare(
    patient_id: str,
    sinocare_id: str,
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
        sinocare = await patient_connected_app_service.add_or_update_sinocare(
            sinocare_id=sinocare_id,
            patient_id=patient_id,
        )  # type: ignore

        sinocare = PatientSinocareSchema.model_validate(sinocare)

        return SuccessResponse(
            message="Sinocare data updated successfully.",
            data=sinocare,
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
    "/libreview/pause",
    response_model=SuccessResponse,
)
async def pause_libreview_sync(
    patient_id: str,
    patient_connected_app_service: PatientConnectedAppService = Depends(
        get_patient_connected_app_service
    ),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.UPDATE, CareProviderFeature.REPORTS
        )
    ),
):
    try:
        libreview = (
            await patient_connected_app_service.pause_libreview_sync(
                patient_id=patient_id,
            )
        )

        libreview_schema = PatientLibreViewSchema.model_validate(libreview)

        return SuccessResponse(
            message="LibreView sync paused successfully.",
            data=libreview_schema,
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
    "/libreview/resume",
    response_model=SuccessResponse,
)
async def resume_libreview_sync(
    patient_id: str,
    patient_connected_app_service: PatientConnectedAppService = Depends(
        get_patient_connected_app_service
    ),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.UPDATE, CareProviderFeature.REPORTS
        )
    ),
):
    try:
        libreview = (
            await patient_connected_app_service.resume_libreview_sync(
                patient_id=patient_id,
            )
        )

        libreview_schema = PatientLibreViewSchema.model_validate(libreview)

        return SuccessResponse(
            message="LibreView sync resumed successfully.",
            data=libreview_schema,
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
    "/sinocare/pause",
    response_model=SuccessResponse,
)
async def pause_sinocare_sync(
    patient_id: str,
    patient_connected_app_service: PatientConnectedAppService = Depends(
        get_patient_connected_app_service
    ),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.UPDATE, CareProviderFeature.REPORTS
        )
    ),
):
    try:
        sinocare = (
            await patient_connected_app_service.pause_sinocare_sync(
                patient_id=patient_id,
            )
        )

        sinocare_schema = PatientSinocareSchema.model_validate(sinocare)

        return SuccessResponse(
            message="Sinocare sync paused successfully.",
            data=sinocare_schema,
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
    "/sinocare/resume",
    response_model=SuccessResponse,
)
async def resume_sinocare_sync(
    patient_id: str,
    patient_connected_app_service: PatientConnectedAppService = Depends(
        get_patient_connected_app_service
    ),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.UPDATE, CareProviderFeature.REPORTS
        )
    ),
):
    try:
        sinocare = (
            await patient_connected_app_service.resume_sinocare_sync(
                patient_id=patient_id,
            )
        )

        sinocare_schema = PatientSinocareSchema.model_validate(sinocare)

        return SuccessResponse(
            message="Sinocare sync resumed successfully.",
            data=sinocare_schema,
        )
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
