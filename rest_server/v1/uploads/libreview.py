from typing import Optional
from uuid import UUID

from fastapi import Depends, File, HTTPException, Query, Request, UploadFile, status

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.patient_access import resolve_patient_access
from lib.dependencies.service_dependencies import (
    get_care_provider_access_service,
    get_cgm_service,
)
from lib.services.care_provider_access_service import CareProviderAccessService
from lib.services.cgm_upload_service import CGMUploadService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.post("/libreview", response_model=SuccessResponse)
async def upload_libreview_csv(
    request: Request,
    file: UploadFile = File(...),
    patient_id: Optional[UUID] = Query(None),
    cgm_upload_service: CGMUploadService = Depends(get_cgm_service),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[
                ProfileTypeEnum.PATIENT,
                ProfileTypeEnum.CARE_PROVIDER,
                ProfileTypeEnum.ADMIN,
            ],
            care_provider_feature=CareProviderFeature.REPORTS,
            care_provider_action=CareProviderPermissionAction.UPDATE,
        )
    ),
):
    try:
        target_patient_id = await resolve_patient_access(
            actor=current_actor,
            patient_id=patient_id,
            care_provider_access_service=care_provider_access_service,
        )

        await cgm_upload_service.parse_and_upload_libreview_raw_csv_data(
            patient_id=str(target_patient_id),
            file_contents=await file.read(),
        )

        return SuccessResponse(
            message="LibreView CGM data uploaded and processed successfully.",
        )

    except HTTPException as http_exc:
        raise http_exc

    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to upload LibreView CGM data",
            detail=str(e),
        )
