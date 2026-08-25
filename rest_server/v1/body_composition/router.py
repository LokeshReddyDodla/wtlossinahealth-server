"""Device-neutral Body Composition API."""

import os
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Query, UploadFile, status

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.patient_access import resolve_patient_access
from lib.dependencies.service_dependencies import (
    get_body_composition_extraction_service,
    get_body_composition_service,
    get_care_provider_access_service,
)
from lib.schemas.body_composition import (
    ConfirmBodyCompositionRequest,
    IngestChannel,
)
from lib.services.body_composition import (
    BodyCompositionExtractionService,
    BodyCompositionService,
)
from lib.services.care_provider_access_service import CareProviderAccessService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from lib.utils.s3_utils import upload_file_to_s3
from rest_server.response_models import SuccessResponse

router = APIRouter(
    prefix="/patients/{patient_id}/body-composition",
    tags=["Body Composition"],
)

_S3_BUCKET = "user-assets.aihealth.clinic"
_ALLOWED_TYPES = {"application/pdf", "image/jpeg", "image/jpg", "image/png"}
_MAX_FILE_BYTES = 15 * 1024 * 1024


def _actor(action: CareProviderPermissionAction):
    return get_current_actor(
        allowed_roles=[
            ProfileTypeEnum.ADMIN,
            ProfileTypeEnum.CARE_PROVIDER,
            ProfileTypeEnum.PATIENT,
        ],
        care_provider_feature=CareProviderFeature.REPORTS,
        care_provider_action=action,
    )


async def _patient_id(
    patient_id: UUID,
    actor: Actor,
    access_service: CareProviderAccessService,
) -> UUID:
    return await resolve_patient_access(
        actor=actor,
        patient_id=patient_id,
        care_provider_access_service=access_service,
    )


@router.post("/preview", response_model=SuccessResponse)
async def preview_body_composition(
    patient_id: UUID,
    file: UploadFile = File(...),
    extraction_service: BodyCompositionExtractionService = Depends(
        get_body_composition_extraction_service
    ),
    service: BodyCompositionService = Depends(get_body_composition_service),
    actor: Actor = Depends(_actor(CareProviderPermissionAction.CREATE)),
    access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    resolved_patient_id = await _patient_id(patient_id, actor, access_service)
    content_type = file.content_type or "application/pdf"
    file_bytes = await file.read()
    if content_type not in _ALLOWED_TYPES:
        raise_http_exception(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="Upload a PDF, JPEG, or PNG body-composition report",
        )
    if not file_bytes or len(file_bytes) > _MAX_FILE_BYTES:
        raise_http_exception(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="Report must be non-empty and no larger than 15 MB",
        )

    extension = os.path.splitext(file.filename or "")[1].lower()
    if extension not in {".pdf", ".jpg", ".jpeg", ".png"}:
        extension = ".pdf" if content_type == "application/pdf" else ".jpg"
    source_file_url = upload_file_to_s3(
        file_bytes=file_bytes,
        bucket_name=_S3_BUCKET,
        file_name=f"{uuid4().hex}{extension}",
        content_type=content_type,
        folder_path=f"patients/{resolved_patient_id}/documents/body-composition",
    )
    if not source_file_url:
        raise_http_exception(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="Failed to upload body-composition report",
        )

    extracted = await extraction_service.extract(
        file_bytes=file_bytes,
        content_type=content_type,
        patient_id=str(resolved_patient_id),
    )
    ingest_channel = (
        IngestChannel.PATIENT_UPLOAD
        if actor.role == ProfileTypeEnum.PATIENT
        else IngestChannel.CARE_PROVIDER_UPLOAD
    )
    record = await service.create_draft(
        patient_id=resolved_patient_id,
        data=extracted,
        ingest_channel=ingest_channel,
        source_file_url=source_file_url,
        original_filename=file.filename,
        content_type=content_type,
        uploaded_by_id=UUID(str(actor.id)) if actor.id else None,
        uploaded_by_type=actor.role.value,
    )
    return SuccessResponse(
        message="Body-composition report extracted for review", data=record
    )


@router.post("/confirm", response_model=SuccessResponse)
async def confirm_body_composition(
    patient_id: UUID,
    payload: ConfirmBodyCompositionRequest,
    service: BodyCompositionService = Depends(get_body_composition_service),
    actor: Actor = Depends(_actor(CareProviderPermissionAction.UPDATE)),
    access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    resolved_patient_id = await _patient_id(patient_id, actor, access_service)
    record = await service.confirm(
        patient_id=resolved_patient_id,
        record_id=UUID(payload.record_id),
        data=payload.data,
        confirmed_by_id=UUID(str(actor.id)) if actor.id else None,
        confirmed_by_type=actor.role.value,
    )
    return SuccessResponse(
        message="Body-composition record confirmed", data=record
    )


@router.get("", response_model=SuccessResponse)
async def list_body_composition(
    patient_id: UUID,
    limit: int = Query(50, ge=1, le=200),
    service: BodyCompositionService = Depends(get_body_composition_service),
    actor: Actor = Depends(_actor(CareProviderPermissionAction.READ)),
    access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    resolved_patient_id = await _patient_id(patient_id, actor, access_service)
    return SuccessResponse(
        message="Body-composition records retrieved",
        data=await service.list_records(resolved_patient_id, limit=limit),
    )


@router.get("/latest", response_model=SuccessResponse)
async def latest_body_composition(
    patient_id: UUID,
    service: BodyCompositionService = Depends(get_body_composition_service),
    actor: Actor = Depends(_actor(CareProviderPermissionAction.READ)),
    access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    resolved_patient_id = await _patient_id(patient_id, actor, access_service)
    return SuccessResponse(
        message="Latest body-composition record retrieved",
        data=await service.get_latest(resolved_patient_id),
    )


@router.get("/trends", response_model=SuccessResponse)
async def body_composition_trends(
    patient_id: UUID,
    limit: int = Query(24, ge=2, le=100),
    service: BodyCompositionService = Depends(get_body_composition_service),
    actor: Actor = Depends(_actor(CareProviderPermissionAction.READ)),
    access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    resolved_patient_id = await _patient_id(patient_id, actor, access_service)
    return SuccessResponse(
        message="Body-composition trends retrieved",
        data=await service.get_trends(resolved_patient_id, limit=limit),
    )


@router.get("/{record_id}", response_model=SuccessResponse)
async def get_body_composition(
    patient_id: UUID,
    record_id: UUID,
    service: BodyCompositionService = Depends(get_body_composition_service),
    actor: Actor = Depends(_actor(CareProviderPermissionAction.READ)),
    access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    resolved_patient_id = await _patient_id(patient_id, actor, access_service)
    return SuccessResponse(
        message="Body-composition record retrieved",
        data=await service.get_record(resolved_patient_id, record_id),
    )


@router.delete("/{record_id}", response_model=SuccessResponse)
async def archive_body_composition(
    patient_id: UUID,
    record_id: UUID,
    service: BodyCompositionService = Depends(get_body_composition_service),
    actor: Actor = Depends(_actor(CareProviderPermissionAction.DELETE)),
    access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    resolved_patient_id = await _patient_id(patient_id, actor, access_service)
    await service.archive(resolved_patient_id, record_id)
    return SuccessResponse(
        message="Body-composition record archived", data=None
    )
