from typing import Optional

from fastapi import Depends, HTTPException, Query, status

from lib.dependencies.auth.care_provider_auth import get_current_care_provider
from lib.dependencies.service_dependencies import (
    get_patient_document_research_service,
)
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.schemas.patient_document_research import (
    PatientDocumentResearchSelectionResponse,
)
from lib.services.patient_document_research_service import (
    PatientDocumentResearchService,
)
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.get(
    "/research/options",
    response_model=SuccessResponse[PatientDocumentResearchSelectionResponse],
    summary="List selectable research sources",
    description="Fetch patient documents, prescriptions, and latest inbody report for research selection.",
)
async def list_research_options(
    patient_id: str,
    document_type: Optional[str] = Query(
        None, description="Filter by document type"
    ),
    uploaded_by_type: Optional[str] = Query(
        None, description="Filter by uploader type (patient or care provider)"
    ),
    order: Optional[str] = Query(
        "asc", description="asc or desc by creation date"
    ),
    patient_document_research_service: PatientDocumentResearchService = Depends(
        get_patient_document_research_service
    ),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.READ, CareProviderFeature.REPORTS
        )
    ),
):
    try:
        result = await patient_document_research_service.fetch_research_selection_options(
            patient_id=patient_id,
            document_type=document_type,
            uploaded_by_type=uploaded_by_type,
            order=order,
        )

        return SuccessResponse(
            message="Research sources fetched successfully",
            data=result,
        )
    except HTTPException as http_exc:
        raise http_exc
    except Exception as exc:  # pragma: no cover
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to fetch research sources",
            detail=str(exc),
        )


