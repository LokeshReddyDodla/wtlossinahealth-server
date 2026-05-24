"""POST /v1/meals/{patient_id}/preview/voice — multipart meal preview with audio.

Same contract as :mod:`preview` but accepts multipart/form-data so the
client can upload an audio file alongside the standard fields. The server
uploads the audio to S3 (for archival), transcribes it via Whisper, and
feeds the transcript into the same ``MealAnalysisAgent`` pipeline.

The S3 audio URL is returned in the response so the client can pass it
back in ``MealCreateRequest.audio_url`` when confirming the meal.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import Depends, File, Form, UploadFile, status
from fastapi.exceptions import HTTPException

from lib.ai_foundation.agents.meal_analysis.agent import MealAnalysisAgent
from lib.ai_foundation.voice.config import voice_settings
from lib.ai_foundation.voice.stt import AudioFormat, SpeechToText
from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.patient_access import resolve_patient_access
from lib.dependencies.service_dependencies import (
    get_care_provider_access_service,
    get_meal_analysis_agent,
    get_speech_to_text,
)
from lib.schemas.meal import MealPreviewRequest, MealSlot, MealSource
from lib.services.care_provider_access_service import CareProviderAccessService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from lib.utils.s3_utils import upload_file_to_s3
from rest_server.response_models import SuccessResponse

from .router import router

logger = logging.getLogger(__name__)

_S3_BUCKET = "user-assets.aihealth.clinic"

_FORMAT_BY_MIME: dict[str, AudioFormat] = {
    "audio/mp4": "m4a",
    "audio/aac": "m4a",
    "audio/x-m4a": "m4a",
    "audio/m4a": "m4a",
    "audio/webm": "webm",
    "audio/ogg": "ogg",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/flac": "flac",
}

_FORMAT_BY_EXTENSION: dict[str, AudioFormat] = {
    ".m4a": "m4a", ".mp4": "mp4", ".aac": "m4a",
    ".webm": "webm", ".ogg": "ogg",
    ".mp3": "mp3", ".mpeg": "mpeg", ".mpga": "mpga",
    ".wav": "wav", ".flac": "flac",
}


def _sniff_audio_format(upload: UploadFile) -> AudioFormat | None:
    if upload.content_type:
        fmt = _FORMAT_BY_MIME.get(upload.content_type.lower())
        if fmt is not None:
            return fmt
    if upload.filename:
        return _FORMAT_BY_EXTENSION.get(Path(upload.filename).suffix.lower())
    return None


@router.post(
    "/{patient_id}/preview/voice",
    response_model=SuccessResponse,
)
async def preview_meal_voice(
    patient_id: str,
    audio: UploadFile = File(..., description="Recorded meal description."),
    slot: MealSlot = Form(...),
    source: MealSource = Form(...),
    consumed_at: datetime | None = Form(None),
    image_url: str | None = Form(None),
    text: str | None = Form(None),
    portion_note: str | None = Form(None),
    agent: MealAnalysisAgent = Depends(get_meal_analysis_agent),
    stt: SpeechToText = Depends(get_speech_to_text),
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[
                ProfileTypeEnum.ADMIN,
                ProfileTypeEnum.CARE_PROVIDER,
                ProfileTypeEnum.PATIENT,
            ],
            care_provider_feature=CareProviderFeature.MEALS,
            care_provider_action=CareProviderPermissionAction.READ,
        )
    ),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    """Analyze a meal with audio input. No DB write — preview only."""
    verified_pid = await resolve_patient_access(
        actor=current_actor,
        patient_id=UUID(patient_id),
        care_provider_access_service=care_provider_access_service,
    )
    pid = str(verified_pid)

    audio_bytes = await audio.read()
    if not audio_bytes:
        raise_http_exception(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="Empty audio upload.",
        )
    if len(audio_bytes) > voice_settings.AUDIO_BUFFER_MAX_BYTES:
        raise_http_exception(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            message=f"Audio exceeds {voice_settings.AUDIO_BUFFER_MAX_BYTES // 1_000_000} MB limit.",
        )

    audio_format = _sniff_audio_format(audio)
    if audio_format is None:
        raise_http_exception(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            message=f"Unsupported audio format: {audio.content_type or audio.filename!r}.",
        )

    s3_task = asyncio.to_thread(
        upload_file_to_s3,
        file_bytes=audio_bytes,
        bucket_name=_S3_BUCKET,
        file_name=f"{uuid4()}.{audio_format}",
        content_type=audio.content_type or f"audio/{audio_format}",
        folder_path=f"patients/{pid}/meals/audio",
    )
    stt_task = stt.transcribe(audio_bytes, audio_format=audio_format)

    audio_url, transcript = await asyncio.gather(s3_task, stt_task, return_exceptions=True)

    if isinstance(transcript, Exception):
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to transcribe audio.",
            detail=str(transcript),
        )
    if isinstance(audio_url, Exception):
        logger.warning("S3 audio upload failed for patient %s: %s", pid, audio_url)
        audio_url = None

    if not transcript.text.strip():
        raise_http_exception(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            message="Could not understand the audio. Please try again.",
        )

    combined_text = f"{text} {transcript.text}" if text else transcript.text

    request = MealPreviewRequest(
        slot=slot,
        source=source,
        consumed_at=consumed_at,
        image_url=image_url,
        text=combined_text,
        portion_note=portion_note,
    )

    try:
        result = await agent.analyze(patient_id=pid, request=request)
        return SuccessResponse(
            message="Meal analyzed",
            data={
                **result.model_dump(mode="json"),
                "audio_url": audio_url,
            },
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise_http_exception(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=str(exc),
        )
    except Exception as exc:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to analyze the meal. Please try again.",
            detail=str(exc),
        )
