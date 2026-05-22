"""POST /consultations/{patient_id}/upload — record audio, transcribe, extract insights."""

from uuid import UUID

from fastapi import Depends, File, UploadFile, status
from fastapi.exceptions import HTTPException

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.patient_access import resolve_patient_access
from lib.dependencies.service_dependencies import (
    get_care_provider_access_service,
    get_consultation_service,
)
from lib.services.care_provider_access_service import CareProviderAccessService
from lib.services.consultation_service import (
    ConsultationService,
    is_supported_audio_mime,
)
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


# 100 MB cap — a 30-min consult at 64 kbps opus is ~14 MB; this leaves headroom
# for higher-bitrate browser recordings without runaway uploads.
_MAX_AUDIO_BYTES = 100 * 1024 * 1024


@router.post(
    "/{patient_id}/upload",
    response_model=SuccessResponse,
)
async def upload_consultation_audio(
    patient_id: str,
    audio: UploadFile = File(..., description="Recorded consultation audio (webm/m4a/mp3/wav/ogg)"),
    consultation_service: ConsultationService = Depends(get_consultation_service),
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
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    """Upload a doctor-patient conversation, transcribe it, extract insights."""
    verified_pid = await resolve_patient_access(
        actor=current_actor,
        patient_id=UUID(patient_id),
        care_provider_access_service=care_provider_access_service,
    )

    if not is_supported_audio_mime(audio.content_type):
        raise_http_exception(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            message=f"Unsupported audio content type: {audio.content_type}",
        )

    audio_bytes = await audio.read()
    if not audio_bytes:
        raise_http_exception(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="Audio file is empty",
        )
    if len(audio_bytes) > _MAX_AUDIO_BYTES:
        raise_http_exception(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            message=f"Audio file exceeds {_MAX_AUDIO_BYTES // (1024 * 1024)} MB limit",
        )

    try:
        consultation = await consultation_service.create_from_audio(
            patient_id=str(verified_pid),
            audio_bytes=audio_bytes,
            original_filename=audio.filename,
            mime_type=audio.content_type,
            recorded_by_id=str(current_actor.id),
            recorded_by_type=current_actor.role.value,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to process consultation recording",
            detail=str(e),
        )

    return SuccessResponse(
        message="Consultation recorded and processed",
        data=consultation.model_dump(mode="json"),
    )
