from fastapi import Depends, File, Query, Request, UploadFile, status

from lib.core.constants import ProfileTypeEnum
from lib.core.types import ReportTypeLiteral
from lib.dependencies.auth.care_provider_auth import get_current_care_provider
from lib.dependencies.service_dependencies import (
    get_cgm_service,
    get_patient_report_service,
)
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.services.cgm_upload_service import CGMUploadService
from lib.services.patient_report_service import PatientReportService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.post("/libreview-raw-csv", response_model=SuccessResponse)
async def upload_libreview_csv(
    request: Request,
    patient_id: str,
    file: UploadFile = File(...),
    cgm_upload_service: CGMUploadService = Depends(get_cgm_service),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.UPDATE, CareProviderFeature.PATIENTS
        )
    ),
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


@router.post("/reports", response_model=SuccessResponse)
async def upload_reports(
    request: Request,
    patient_id: str,
    report_type: ReportTypeLiteral,
    file: UploadFile = File(...),
    patient_report_service: PatientReportService = Depends(
        get_patient_report_service
    ),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.UPDATE, CareProviderFeature.PATIENTS
        )
    ),
):
    try:
        result = await patient_report_service.upload_patient_report(
            patient_id=patient_id,
            file_bytes=await file.read(),
            file_name=file.filename,
            content_type=file.content_type,
            report_type=report_type,
            uploaded_by_id=str(current_care_provider.care_provider_id),
            uploaded_by_type=ProfileTypeEnum.CARE_PROVIDER.value,
        )  # type: ignore

        return SuccessResponse(
            message="Report upload successfully.",
            data={
                "conversation_id": f"{result.report_id}-{current_care_provider.care_provider_id}"
            },
        )

    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
