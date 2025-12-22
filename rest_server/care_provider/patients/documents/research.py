from fastapi import Depends, HTTPException, status

from lib.dependencies.auth.care_provider_auth import get_current_care_provider
from lib.dependencies.service_dependencies import (
    get_patient_document_research_service,
)
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.schemas.patient_document_research import (
    PatientDocumentResearchChatRequest,
    PatientDocumentResearchChatResponse,
    PatientDocumentResearchSummaryRequest,
    PatientDocumentResearchSummaryResponse,
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


@router.post(
    "/research/summary",
    response_model=SuccessResponse[PatientDocumentResearchSummaryResponse],
    summary="Generate research summary",
    description=(
        "Combine selected patient documents into an AI-generated research summary and start a conversation context."
    ),
)
async def summarize_patient_documents_for_research(
    patient_id: str,
    request: PatientDocumentResearchSummaryRequest,
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
        result = await patient_document_research_service.generate_research_summary(
            patient_id=patient_id,
            care_provider_id=str(current_care_provider.care_provider_id),
            request=request,
        )

        return SuccessResponse(
            message="Patient document research summary generated successfully",
            data=result,
        )
    except HTTPException as http_exc:
        raise http_exc
    except Exception as exc:  # pragma: no cover
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to summarize patient documents",
            detail=str(exc),
        )


@router.post(
    "/research/chat",
    response_model=SuccessResponse[PatientDocumentResearchChatResponse],
    summary="Ask questions about selected documents",
    description="Ask follow-up questions about the previously summarized patient documents.",
)
async def chat_about_patient_documents(
    patient_id: str,
    request: PatientDocumentResearchChatRequest,
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
        result = await patient_document_research_service.chat_about_documents(
            patient_id=patient_id,
            care_provider_id=str(current_care_provider.care_provider_id),
            request=request,
        )

        return SuccessResponse(
            message="Question answered successfully",
            data=result,
        )
    except HTTPException as http_exc:
        raise http_exc
    except Exception as exc:  # pragma: no cover
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to answer question about documents",
            detail=str(exc),
        )
