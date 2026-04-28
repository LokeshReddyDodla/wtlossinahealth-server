"""REST routes for the unified Profile Agent."""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, File, Query, UploadFile

from lib.core.constants import ProfileTypeEnum
from lib.core.types import DocumentTypeLiteral
from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.service_dependencies import (
    get_patient_document_service,
    get_profile_agent_documents_service,
    get_profile_agent_service,
)
from lib.models.patient import Patient
from lib.schemas.profile_agent import (
    GapReport,
    ProfileAgentChatRequest,
    ProfileAgentChatResponse,
    ProfileAgentStartRequest,
    SessionSummaryResponse,
)
from lib.schemas.profile_agent_documents import (
    DeleteDocumentResponse,
    DocumentDetail,
    DocumentSummary,
    OverviewResponse,
    SkipDocumentsResponse,
    StartDocumentsResponse,
    TimelineResponse,
    UploadResultItem,
)
from lib.services.patient_document_service import PatientDocumentService
from lib.services.profile_agent import ProfileAgentService
from lib.services.profile_agent.documents.service import (
    ProfileAgentDocumentsService,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

router = APIRouter(
    prefix="/profile-agent",
    tags=["Profile Agent"],
)


@router.post(
    "/start",
    response_model=SuccessResponse[ProfileAgentChatResponse],
    summary="Start or resume a profile-agent session",
)
async def start_session(
    body: ProfileAgentStartRequest,
    current_patient: Patient = Depends(get_current_patient),
    service: ProfileAgentService = Depends(get_profile_agent_service),
) -> SuccessResponse[ProfileAgentChatResponse]:
    result = await service.start(
        patient_id=str(current_patient.patient_id),
        restart=body.restart,
    )
    return SuccessResponse(data=result, message="Profile agent ready")


@router.post(
    "/chat",
    response_model=SuccessResponse[ProfileAgentChatResponse],
    summary="Send a turn to the profile agent",
)
async def chat(
    body: ProfileAgentChatRequest,
    current_patient: Patient = Depends(get_current_patient),
    service: ProfileAgentService = Depends(get_profile_agent_service),
) -> SuccessResponse[ProfileAgentChatResponse]:
    result = await service.chat(
        patient_id=str(current_patient.patient_id),
        message=body.message,
    )
    return SuccessResponse(data=result, message="Profile agent response")


@router.get(
    "/session",
    response_model=SuccessResponse[Optional[SessionSummaryResponse]],
    summary="Get the active profile-agent session",
)
async def get_session(
    current_patient: Patient = Depends(get_current_patient),
    service: ProfileAgentService = Depends(get_profile_agent_service),
) -> SuccessResponse[Optional[SessionSummaryResponse]]:
    result = await service.get_active_session(
        patient_id=str(current_patient.patient_id),
    )
    return SuccessResponse(
        data=result,
        message="Active session retrieved" if result else "No active session",
    )


@router.get(
    "/gaps",
    response_model=SuccessResponse[GapReport],
    summary="Report profile completeness and next missing fields",
)
async def get_gaps(
    current_patient: Patient = Depends(get_current_patient),
    service: ProfileAgentService = Depends(get_profile_agent_service),
) -> SuccessResponse[GapReport]:
    result = await service.get_gaps(
        patient_id=str(current_patient.patient_id),
    )
    return SuccessResponse(data=result, message="Profile gap report")


# ─── Medical documents (post-onboarding) ───────────────────────────────


@router.post(
    "/documents/start",
    response_model=SuccessResponse[StartDocumentsResponse],
    summary="Greet the patient and report their documents-section status",
)
async def documents_start(
    current_patient: Patient = Depends(get_current_patient),
    documents_service: ProfileAgentDocumentsService = Depends(
        get_profile_agent_documents_service
    ),
) -> SuccessResponse[StartDocumentsResponse]:
    result = await documents_service.start(str(current_patient.patient_id))
    return SuccessResponse(data=result, message="Documents agent ready")


@router.post(
    "/documents/upload",
    response_model=SuccessResponse[List[UploadResultItem]],
    summary="Upload one or more medical documents (multipart)",
)
async def documents_upload(
    document_type: DocumentTypeLiteral = "report",
    files: List[UploadFile] = File(...),
    current_patient: Patient = Depends(get_current_patient),
    patient_document_service: PatientDocumentService = Depends(
        get_patient_document_service
    ),
) -> SuccessResponse[List[UploadResultItem]]:
    result = await patient_document_service.upload_multiple_documents(
        patient_id=str(current_patient.patient_id),
        files=files,
        document_type=document_type,
        uploaded_by_id=str(current_patient.patient_id),
        uploaded_by_type=ProfileTypeEnum.PATIENT.value,  # type: ignore
    )
    return SuccessResponse(
        data=[UploadResultItem(**item) for item in result],
        message="Documents uploaded",
    )


@router.get(
    "/documents",
    response_model=SuccessResponse[List[DocumentSummary]],
    summary="List the patient's medical documents",
)
async def documents_list(
    category: Optional[str] = Query(None),
    order: Optional[str] = Query("desc"),
    limit: Optional[int] = Query(50),
    offset: int = Query(0),
    current_patient: Patient = Depends(get_current_patient),
    documents_service: ProfileAgentDocumentsService = Depends(
        get_profile_agent_documents_service
    ),
) -> SuccessResponse[List[DocumentSummary]]:
    items = await documents_service.list_documents(
        patient_id=str(current_patient.patient_id),
        category=category,
        order=order,
        limit=limit,
        offset=offset,
    )
    return SuccessResponse(data=items, message="Documents fetched")


@router.get(
    "/documents/timeline",
    response_model=SuccessResponse[TimelineResponse],
    summary="Chronological timeline of documents with cross-document link groups",
)
async def documents_timeline(
    current_patient: Patient = Depends(get_current_patient),
    documents_service: ProfileAgentDocumentsService = Depends(
        get_profile_agent_documents_service
    ),
) -> SuccessResponse[TimelineResponse]:
    result = await documents_service.timeline(str(current_patient.patient_id))
    return SuccessResponse(data=result, message="Documents timeline")


@router.get(
    "/documents/overview",
    response_model=SuccessResponse[OverviewResponse],
    summary="Cross-document patient overview (narrative + link groups)",
)
async def documents_overview(
    current_patient: Patient = Depends(get_current_patient),
    documents_service: ProfileAgentDocumentsService = Depends(
        get_profile_agent_documents_service
    ),
) -> SuccessResponse[OverviewResponse]:
    result = await documents_service.overview(str(current_patient.patient_id))
    if result is None:
        raise_http_exception(404, "Overview not generated yet")
    return SuccessResponse(data=result, message="Documents overview")


@router.post(
    "/documents/skip",
    response_model=SuccessResponse[SkipDocumentsResponse],
    summary="Mark the documents onboarding section as complete (skipped)",
)
async def documents_skip(
    current_patient: Patient = Depends(get_current_patient),
    documents_service: ProfileAgentDocumentsService = Depends(
        get_profile_agent_documents_service
    ),
) -> SuccessResponse[SkipDocumentsResponse]:
    result = await documents_service.skip(str(current_patient.patient_id))
    return SuccessResponse(data=result, message="Documents step skipped")


@router.get(
    "/documents/{document_id}",
    response_model=SuccessResponse[DocumentDetail],
    summary="Fetch a single document (metadata + findings + download URL)",
)
async def documents_detail(
    document_id: str,
    current_patient: Patient = Depends(get_current_patient),
    documents_service: ProfileAgentDocumentsService = Depends(
        get_profile_agent_documents_service
    ),
) -> SuccessResponse[DocumentDetail]:
    result = await documents_service.get_document(
        patient_id=str(current_patient.patient_id),
        document_id=document_id,
    )
    return SuccessResponse(data=result, message="Document fetched")


@router.delete(
    "/documents/{document_id}",
    response_model=SuccessResponse[DeleteDocumentResponse],
    summary="Soft-delete a document and remove its underlying file",
)
async def documents_delete(
    document_id: str,
    current_patient: Patient = Depends(get_current_patient),
    documents_service: ProfileAgentDocumentsService = Depends(
        get_profile_agent_documents_service
    ),
) -> SuccessResponse[DeleteDocumentResponse]:
    await documents_service.delete(
        patient_id=str(current_patient.patient_id),
        document_id=document_id,
    )
    return SuccessResponse(
        data=DeleteDocumentResponse(deleted=True), message="Document deleted"
    )
