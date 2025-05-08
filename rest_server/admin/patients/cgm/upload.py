from fastapi import APIRouter, Depends, File, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from lib.dependencies.auth.admin_auth import get_current_admin
from lib.dependencies.database import get_postgres_session
from lib.dependencies.service_dependencies import get_cgm_service
from lib.models.admin import Admin
from lib.services.cgm_upload_service import CGMUploadService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

router = APIRouter(prefix="/admin/patient")


@router.post("/upload/libreview-raw-csv", tags=["Admin Patient"])
async def admin_upload_libreview_raw_csv(
    request: Request,
    patient_id: str,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_postgres_session),
    cgm_upload_service: CGMUploadService = Depends(get_cgm_service),
    current_admin: Admin = Depends(get_current_admin),
):
    try:
        await cgm_upload_service.parse_and_upload_cgm_data(
            patient_id=str(patient_id),
            file_contents=await file.read(),
        )

        return SuccessResponse(message="CGM data uploaded and stored successfully.")

    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
