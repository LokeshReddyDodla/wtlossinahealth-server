from typing import Union
from uuid import UUID

from fastapi import Depends, HTTPException, Query, Request, status

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.patient_access import resolve_patient_access
from lib.dependencies.service_dependencies import (
    get_care_provider_access_service,
    get_libreview_service,
    get_patient_connected_app_service,
)
from lib.models.patient import Patient
from lib.services.care_provider_access_service import CareProviderAccessService
from lib.schemas.patient_connected_app import (
    PatientLibreView as PatientLibreViewSchema,
)
from lib.schemas.patient_connected_app import PatientLibreViewCreate
from lib.services.libreview_service import LibreViewService
from lib.services.patient_connected_app_service import (
    PatientConnectedAppService,
)
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
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[
                ProfileTypeEnum.PATIENT,
                ProfileTypeEnum.CARE_PROVIDER,
                ProfileTypeEnum.ADMIN,
            ],
            check_permissions=False,
        )
    ),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    try:
        # A patient may sync only their own; a care provider only an assigned patient.
        verified_patient_id = await resolve_patient_access(
            actor=current_actor,
            patient_id=UUID(patient_id),
            care_provider_access_service=care_provider_access_service,
        )
        result = await libreview_service.sync_libreview(str(verified_patient_id), force=force)

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


@router.post(
    "/libreview/pause",
    response_model=SuccessResponse,
)
async def pause_libreview_sync(
    request: Request,
    patient_connected_app_service: PatientConnectedAppService = Depends(
        get_patient_connected_app_service
    ),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        libreview = (
            await patient_connected_app_service.pause_libreview_sync(
                patient_id=str(current_patient.patient_id),
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
    request: Request,
    patient_connected_app_service: PatientConnectedAppService = Depends(
        get_patient_connected_app_service
    ),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        libreview = (
            await patient_connected_app_service.resume_libreview_sync(
                patient_id=str(current_patient.patient_id),
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
