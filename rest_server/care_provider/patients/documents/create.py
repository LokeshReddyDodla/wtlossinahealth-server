from typing import List
from fastapi import Depends, File, Query, Request, UploadFile, status

from lib.core.constants import ProfileTypeEnum
from lib.core.types import DocumentTypeLiteral
from lib.dependencies.auth.care_provider_auth import get_current_care_provider
from lib.dependencies.service_dependencies import (
    get_cgm_service,
    get_patient_document_service,
)
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.services.patient_document_service import PatientDocumentService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.post("/upload", response_model=SuccessResponse)
async def upload_documents(
    request: Request,
    patient_id: str,
    document_type: DocumentTypeLiteral,
    files: List[UploadFile] = File(...),
    patient_document_service: PatientDocumentService = Depends(
        get_patient_document_service
    ),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.UPDATE, CareProviderFeature.PATIENTS
        )
    ),
):
    try:
        result = await patient_document_service.upload_multiple_documents(
            patient_id=patient_id,
            files=files,
            document_type=document_type,
            uploaded_by_id=str(current_care_provider.care_provider_id),
            uploaded_by_type=ProfileTypeEnum.CARE_PROVIDER.value,  # type: ignore
        )

        return SuccessResponse(
            message="Report upload successfully.",
            data=result,
        )

    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
