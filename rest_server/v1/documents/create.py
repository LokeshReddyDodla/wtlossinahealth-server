from typing import List
from uuid import UUID

from fastapi import Depends, File, Form, HTTPException, UploadFile, status

from lib.core.constants import ProfileTypeEnum
from lib.core.types import DocumentTypeLiteral
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.patient_access import resolve_patient_access
from lib.dependencies.service_dependencies import (
    get_care_provider_access_service,
    get_patient_document_service,
)
from lib.services.care_provider_access_service import CareProviderAccessService
from lib.services.patient_document_service import PatientDocumentService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.post("/{patient_id}/upload", response_model=SuccessResponse)
async def upload_documents(
    patient_id: str,
    document_type: DocumentTypeLiteral = Form(...),
    files: List[UploadFile] = File(...),
    patient_document_service: PatientDocumentService = Depends(
        get_patient_document_service
    ),
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
            care_provider_feature=CareProviderFeature.PATIENTS,
            care_provider_action=CareProviderPermissionAction.UPDATE,
        )
    ),
):
    try:
        verified_pid = await resolve_patient_access(
            actor=current_actor,
            patient_id=UUID(patient_id) if patient_id else None,
            care_provider_access_service=care_provider_access_service,
        )

        result = await patient_document_service.upload_multiple_documents(
            patient_id=str(verified_pid),
            files=files,
            document_type=document_type,
            uploaded_by_id=current_actor.id,
            uploaded_by_type=current_actor.role.value,  # type: ignore[arg-type]
        )

        return SuccessResponse(
            message="Documents uploaded successfully.",
            data=result,
        )

    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to upload documents.",
            detail=str(e),
        )
