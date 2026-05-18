from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, Query, status

from lib.core.constants import ProfileTypeEnum
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


@router.get("/{patient_id}", response_model=SuccessResponse)
async def list_documents(
    patient_id: str,
    document_type: Optional[str] = Query(
        None, description="Filter by document type"
    ),
    uploaded_by_type: Optional[str] = Query(
        None,
        description="Filter by uploader type (patient, care_provider, admin)",
    ),
    order: Optional[str] = Query(
        "asc", description="asc or desc by creation date"
    ),
    limit: Optional[int] = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
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
            care_provider_feature=CareProviderFeature.REPORTS,
            care_provider_action=CareProviderPermissionAction.READ,
        )
    ),
):
    try:
        verified_pid = await resolve_patient_access(
            actor=current_actor,
            patient_id=UUID(patient_id) if patient_id else None,
            care_provider_access_service=care_provider_access_service,
        )

        documents = await patient_document_service.fetch_patient_documents(
            patient_id=str(verified_pid),
            document_type=document_type,
            uploaded_by_type=uploaded_by_type,
            order=order,
            limit=limit,
            offset=offset,
        )

        return SuccessResponse(
            message="Documents fetched successfully.",
            data=documents,
        )

    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to fetch documents.",
            detail=str(e),
        )
