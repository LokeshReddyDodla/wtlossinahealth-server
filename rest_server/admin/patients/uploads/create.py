from fastapi import Depends, File, Query, Request, UploadFile, status

from lib.dependencies.auth.admin_auth import get_current_admin
from lib.dependencies.auth.care_provider_auth import get_current_care_provider
from lib.dependencies.service_dependencies import get_cgm_service
from lib.models.admin import Admin
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.services.cgm_upload_service import CGMUploadService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.post("/libreview-raw-csv", response_model=SuccessResponse)
async def upload_libreview_raw_csv(
    request: Request,
    patient_id: str = Query(...),
    file: UploadFile = File(...),
    cgm_upload_service: CGMUploadService = Depends(get_cgm_service),
    current_admin: Admin = Depends(get_current_admin),
):
    try:
        await cgm_upload_service.parse_and_upload_libreview_raw_csv_data(
            patient_id=patient_id,
            file_contents=await file.read(),
        )

        return SuccessResponse(
            message="CGM data uploaded and stored successfully."
        )

    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
