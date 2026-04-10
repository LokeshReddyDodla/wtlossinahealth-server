"""POST /prescriptions/{patient_id}/preview — upload, extract, and save as draft."""

from typing import List

from fastapi import Depends, UploadFile, File, status

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.dependencies.service_dependencies import (
    get_medication_service,
    get_prescription_extraction_service,
)
from lib.services.medication_service import MedicationService
from lib.services.prescription_extraction_service import PrescriptionExtractionService
from lib.utils.s3_utils import upload_file_to_s3
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
    medication_service: MedicationService = Depends(get_medication_service),
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[
                ProfileTypeEnum.ADMIN,
                ProfileTypeEnum.CARE_PROVIDER,
                ProfileTypeEnum.PATIENT,
            ],
            care_provider_feature=CareProviderFeature.REPORTS,
            care_provider_action=CareProviderPermissionAction.CREATE,
        )
    ),
):
    """Upload prescription images, extract structured data, save as draft."""
    try:
        # Upload to S3
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

        # Extract via LLM
        extracted = await extraction_service.extract(image_urls=file_urls)

        # Validate — must look like an actual prescription
        if not extracted.medicines:
            raise_http_exception(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="This doesn't look like a prescription. Please upload a clear image of a medical prescription.",
            )

        # Save as draft
        draft = await medication_service.save_draft_prescription(
            patient_id=patient_id,
            file_urls=file_urls,
            extracted_data=extracted.model_dump(mode="json"),
            uploaded_by_id=str(current_actor.id),
            uploaded_by_type=current_actor.role.value,
        )

        return SuccessResponse(
            message="Prescription uploaded and saved as draft",
            data={
                "prescription_id": str(draft.prescription_id),
                "file_urls": file_urls,
                "status": draft.status,
                "extracted": extracted.model_dump(mode="json"),
            },
        )
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to extract prescription data",
            detail=str(e),
        )
