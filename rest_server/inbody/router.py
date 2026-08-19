"""Patient-level InBody report endpoints.

Accessible to the patient themselves and to care providers with access to
the patient — both resolved through ``resolve_patient_access``.
"""

from datetime import date
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.patient_access import resolve_patient_access
from lib.dependencies.service_dependencies import (
    get_care_provider_access_service,
    get_inbody_attribution_service,
    get_inbody_day_summary_service,
    get_inbody_report_service,
    get_inbody_trends_service,
)
from lib.services.care_provider_access_service import CareProviderAccessService
from lib.services.inbody.service import InbodyReportService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from rest_server.response_models import SuccessResponse

router = APIRouter(
    prefix="/patients/{patient_id}/inbody-reports", tags=["InBody Reports"]
)


def _actor_dependency(action: CareProviderPermissionAction):
    return get_current_actor(
        allowed_roles=[
            ProfileTypeEnum.PATIENT,
            ProfileTypeEnum.CARE_PROVIDER,
        ],
        care_provider_feature=CareProviderFeature.PATIENTS,
        care_provider_action=action,
    )


@router.post(
    "",
    response_model=SuccessResponse[dict],
    status_code=status.HTTP_201_CREATED,
    summary="Upload an InBody report",
    description=(
        "Upload an InBody result sheet (PDF/JPEG/PNG). The file is stored "
        "and its measurements extracted into structured data. Reports with "
        "low extraction confidence are flagged needs_review."
    ),
)
async def upload_inbody_report(
    patient_id: UUID,
    report_file: UploadFile = File(...),
    report_date: Optional[str] = Form(
        None, description="ISO date printed on the scan, if known"
    ),
    inbody_service: InbodyReportService = Depends(get_inbody_report_service),
    actor: Actor = Depends(
        _actor_dependency(CareProviderPermissionAction.CREATE)
    ),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    resolved_patient_id = await resolve_patient_access(
        actor=actor,
        patient_id=patient_id,
        care_provider_access_service=care_provider_access_service,
    )

    parsed_date = date.fromisoformat(report_date) if report_date else None
    file_bytes = await report_file.read()

    report = await inbody_service.upload_report(
        patient_id=resolved_patient_id,
        file_bytes=file_bytes,
        original_filename=report_file.filename,
        content_type=report_file.content_type or "application/pdf",
        report_date=parsed_date,
        uploaded_by_role=actor.role.value,
        uploaded_by_id=UUID(str(actor.id)) if actor.id else None,
    )

    return SuccessResponse(
        status="success",
        message="InBody report uploaded and processed",
        data=report,
    )


@router.get(
    "",
    response_model=SuccessResponse[List[dict]],
    summary="List InBody reports",
)
async def list_inbody_reports(
    patient_id: UUID,
    limit: int = Query(50, ge=1, le=200),
    inbody_service: InbodyReportService = Depends(get_inbody_report_service),
    actor: Actor = Depends(
        _actor_dependency(CareProviderPermissionAction.READ)
    ),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    resolved_patient_id = await resolve_patient_access(
        actor=actor,
        patient_id=patient_id,
        care_provider_access_service=care_provider_access_service,
    )
    reports = await inbody_service.list_reports(resolved_patient_id, limit)
    return SuccessResponse(
        status="success",
        message="InBody reports retrieved",
        data=reports,
    )


@router.get(
    "/latest",
    response_model=SuccessResponse[Optional[dict]],
    summary="Get latest InBody report with analysis",
)
async def get_latest_inbody_report(
    patient_id: UUID,
    inbody_service: InbodyReportService = Depends(get_inbody_report_service),
    actor: Actor = Depends(
        _actor_dependency(CareProviderPermissionAction.READ)
    ),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    resolved_patient_id = await resolve_patient_access(
        actor=actor,
        patient_id=patient_id,
        care_provider_access_service=care_provider_access_service,
    )
    report = await inbody_service.get_latest_report(resolved_patient_id)
    return SuccessResponse(
        status="success",
        message=(
            "Latest InBody report retrieved"
            if report
            else "No InBody reports found"
        ),
        data=report,
    )


@router.get(
    "/trends",
    response_model=SuccessResponse[dict],
    summary="Get scan-over-scan body-composition trends",
    description=(
        "Deterministic time series computed from the stored extractions: "
        "per-metric series, latest-vs-previous deltas and overall change. "
        "No LLM involved."
    ),
)
async def get_inbody_trends(
    patient_id: UUID,
    limit: int = Query(24, ge=2, le=100),
    trends_service=Depends(get_inbody_trends_service),
    actor: Actor = Depends(
        _actor_dependency(CareProviderPermissionAction.READ)
    ),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    resolved_patient_id = await resolve_patient_access(
        actor=actor,
        patient_id=patient_id,
        care_provider_access_service=care_provider_access_service,
    )
    trends = await trends_service.get_trends(resolved_patient_id, limit)
    return SuccessResponse(
        status="success",
        message="InBody trends computed",
        data=trends,
    )


@router.get(
    "/attribution/latest",
    response_model=SuccessResponse[Optional[dict]],
    summary="Get the latest scan-attribution analysis",
    description=(
        "The health agent's explanation of what drove the change between "
        "the patient's two most recent scans. Generated by a background job "
        "after each extraction; this endpoint only reads it."
    ),
)
async def get_latest_inbody_attribution(
    patient_id: UUID,
    attribution_service=Depends(get_inbody_attribution_service),
    actor: Actor = Depends(
        _actor_dependency(CareProviderPermissionAction.READ)
    ),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    resolved_patient_id = await resolve_patient_access(
        actor=actor,
        patient_id=patient_id,
        care_provider_access_service=care_provider_access_service,
    )
    analysis = await attribution_service.get_latest(resolved_patient_id)
    return SuccessResponse(
        status="success",
        message=(
            "Latest InBody attribution retrieved"
            if analysis
            else "No InBody attribution yet"
        ),
        data=analysis,
    )


@router.get(
    "/{report_id}/attribution",
    response_model=SuccessResponse[Optional[dict]],
    summary="Get the scan-attribution analysis for one report",
    description=(
        "Attribution for a specific scan. If none exists yet for a usable "
        "report, generation is enqueued and status 'generating' is returned "
        "so the client can poll."
    ),
)
async def get_inbody_report_attribution(
    patient_id: UUID,
    report_id: UUID,
    attribution_service=Depends(get_inbody_attribution_service),
    inbody_service: InbodyReportService = Depends(get_inbody_report_service),
    actor: Actor = Depends(
        _actor_dependency(CareProviderPermissionAction.READ)
    ),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    resolved_patient_id = await resolve_patient_access(
        actor=actor,
        patient_id=patient_id,
        care_provider_access_service=care_provider_access_service,
    )
    analysis = await attribution_service.get_for_report(
        resolved_patient_id, report_id
    )
    if analysis:
        return SuccessResponse(
            status="success",
            message="InBody attribution retrieved",
            data=analysis,
        )

    # Self-heal: no analysis yet — enqueue generation for usable reports.
    enqueued = await inbody_service.request_attribution(
        resolved_patient_id, report_id
    )
    return SuccessResponse(
        status="success",
        message=(
            "InBody attribution is being generated"
            if enqueued
            else "Report has no usable extraction to analyze"
        ),
        data={"status": "generating"} if enqueued else None,
    )


@router.get(
    "/{report_id}",
    response_model=SuccessResponse[dict],
    summary="Get one InBody report with analysis",
)
async def get_inbody_report(
    patient_id: UUID,
    report_id: UUID,
    inbody_service: InbodyReportService = Depends(get_inbody_report_service),
    actor: Actor = Depends(
        _actor_dependency(CareProviderPermissionAction.READ)
    ),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    resolved_patient_id = await resolve_patient_access(
        actor=actor,
        patient_id=patient_id,
        care_provider_access_service=care_provider_access_service,
    )
    report = await inbody_service.get_report_detail(
        resolved_patient_id, report_id
    )
    return SuccessResponse(
        status="success",
        message="InBody report retrieved",
        data=report,
    )


@router.get(
    "/day-summary/latest",
    response_model=SuccessResponse[Optional[dict]],
    summary="Get the latest InBody daily summary",
    description=(
        "The most recent end-of-day summary generated by the health agent "
        "for this patient. Generated by a background job; this endpoint only "
        "reads it."
    ),
)
async def get_latest_inbody_day_summary(
    patient_id: UUID,
    summary_service=Depends(get_inbody_day_summary_service),
    actor: Actor = Depends(
        _actor_dependency(CareProviderPermissionAction.READ)
    ),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    resolved_patient_id = await resolve_patient_access(
        actor=actor,
        patient_id=patient_id,
        care_provider_access_service=care_provider_access_service,
    )
    summary = await summary_service.get_latest(resolved_patient_id)
    return SuccessResponse(
        status="success",
        message=(
            "Latest InBody day summary retrieved"
            if summary
            else "No InBody day summary yet"
        ),
        data=summary,
    )


@router.get(
    "/day-summary/{summary_date}",
    response_model=SuccessResponse[Optional[dict]],
    summary="Get the InBody daily summary for a specific date",
)
async def get_inbody_day_summary_for_date(
    patient_id: UUID,
    summary_date: date,
    summary_service=Depends(get_inbody_day_summary_service),
    actor: Actor = Depends(
        _actor_dependency(CareProviderPermissionAction.READ)
    ),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    resolved_patient_id = await resolve_patient_access(
        actor=actor,
        patient_id=patient_id,
        care_provider_access_service=care_provider_access_service,
    )
    summary = await summary_service.get_for_date(
        resolved_patient_id, summary_date
    )
    return SuccessResponse(
        status="success",
        message=(
            "InBody day summary retrieved"
            if summary
            else "No InBody day summary for that date"
        ),
        data=summary,
    )
