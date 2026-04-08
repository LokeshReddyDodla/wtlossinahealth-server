"""POST /prescriptions/{patient_id}/preview — extract structured data from prescription images."""

from typing import List

from fastapi import Depends, UploadFile, File, status

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.service_dependencies import get_prescription_extraction_service
from lib.services.prescription_extraction_service import PrescriptionExtractionService
from lib.utils.s3_utils import upload_file_to_s3
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router

_S3_BUCKET = "user-assets.aihealth.clinic"


@router.post(
    "/{patient_id}/preview",
    response_model=SuccessResponse,
)
async def preview_prescription(
    patient_id: str,
    files: List[UploadFile] = File(...),
    extraction_service: PrescriptionExtractionService = Depends(
        get_prescription_extraction_service
    ),
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[
                ProfileTypeEnum.ADMIN,
                ProfileTypeEnum.CARE_PROVIDER,
            ],
            care_provider_feature=CareProviderFeature.REPORTS,
            care_provider_action=CareProviderPermissionAction.CREATE,
        )
    ),
):
    """Upload one or more prescription images, extract structured data for confirmation."""
    try:
        file_urls = []
        for file in files:
            file_bytes = await file.read()
            file_url = upload_file_to_s3(
                file_bytes=file_bytes,
                bucket_name=_S3_BUCKET,
                file_name=file.filename or "prescription.jpg",
                content_type=file.content_type or "image/jpeg",
                folder_path=f"patients/{patient_id}/documents/prescription",
            )
            if file_url:
                file_urls.append(file_url)

        if not file_urls:
            raise_http_exception(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Failed to upload prescription files",
            )

        extracted = await extraction_service.extract(image_urls=file_urls)

        return SuccessResponse(
            message="Prescription data extracted successfully",
            data={
                "file_urls": file_urls,
                "extracted": extracted.model_dump(mode="json"),
            },
        )
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to extract prescription data",
            detail=str(e),
        )
