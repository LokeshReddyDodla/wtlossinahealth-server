"""Voice-based workout logging endpoint.

Accepts audio + current session state. Returns the updated session with
the latest voice input interpreted, exercises matched from catalog, and
sets/reps parsed.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import Depends, File, Form, UploadFile, status

from lib.ai_foundation.voice.config import voice_settings
from lib.ai_foundation.voice.stt import AudioFormat
from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.patient_access import resolve_patient_access
from lib.dependencies.service_dependencies import (
    get_care_provider_access_service,
    get_workout_voice_service,
)
from lib.schemas.workout_voice import WorkoutVoiceSessionState
from lib.services.care_provider_access_service import CareProviderAccessService
from lib.services.workout_voice_service import EmptyTranscriptError, WorkoutVoiceService
from lib.utils.http_exceptions import raise_http_exception
from lib.utils.s3_utils import upload_file_to_s3
from rest_server.response_models import SuccessResponse

from .router import router

logger = logging.getLogger(__name__)

S3_BUCKET = "user-assets.aihealth.clinic"

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

_ACTOR_DEPS = dict(
    allowed_roles=[
        ProfileTypeEnum.PATIENT,
        ProfileTypeEnum.CARE_PROVIDER,
        ProfileTypeEnum.ADMIN,
    ],
    check_permissions=False,
)


def _sniff_audio_format(upload: UploadFile) -> AudioFormat | None:
    if upload.content_type:
        fmt = _FORMAT_BY_MIME.get(upload.content_type.lower())
        if fmt is not None:
            return fmt
    if upload.filename:
        return _FORMAT_BY_EXTENSION.get(Path(upload.filename).suffix.lower())
    return None


@router.post(
    "/{patient_id}/workouts/voice",
    response_model=SuccessResponse,
)
async def workout_voice_input(
    patient_id: str,
    audio: UploadFile = File(..., description="Voice input from the gym."),
    session_state: str = Form(
        "{}",
        description="JSON-encoded WorkoutVoiceSessionState — current exercises/sets so far.",
    ),
    text: str | None = Form(None, description="Optional text alongside audio."),
    service: WorkoutVoiceService = Depends(get_workout_voice_service),
    current_actor: Actor = Depends(get_current_actor(**_ACTOR_DEPS)),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    """Process a single voice input during a workout session.

    The frontend sends the running session state with each call.
    The server interprets the audio, matches exercises, and returns
    the updated session state.
    """
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

    try:
        session = WorkoutVoiceSessionState.model_validate_json(session_state)
    except Exception:
        raise_http_exception(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="Invalid session_state JSON.",
        )

    logger.info(
        "[WorkoutVoice] ← INCOMING voice | patient=%s | audio=%s %dB | text=%r | session_exercises=%d [%s]",
        pid,
        audio_format,
        len(audio_bytes),
        text,
        len(session.exercises),
        ", ".join(f"{e.exercise_name}({len(e.sets)}s)" for e in session.exercises),
    )

    s3_task = asyncio.to_thread(
        upload_file_to_s3,
        file_bytes=audio_bytes,
        bucket_name=S3_BUCKET,
        file_name=f"{uuid4()}.{audio_format}",
        content_type=audio.content_type or f"audio/{audio_format}",
        folder_path=f"patients/{pid}/workouts/audio",
    )

    result, audio_url = await asyncio.gather(
        service.process_voice_input(
            audio_bytes=audio_bytes,
            audio_format=audio_format,
            session=session,
            text=text,
            patient_id=pid,
        ),
        s3_task,
        return_exceptions=True,
    )

    if isinstance(result, EmptyTranscriptError):
        raise_http_exception(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            message=str(result),
        )
    if isinstance(result, Exception):
        logger.error("Workout voice processing failed: %s", result)
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to process voice input.",
            detail=str(result),
        )

    if isinstance(audio_url, Exception):
        logger.warning("S3 upload failed for patient %s workout audio: %s", pid, audio_url)
        audio_url = None

    result.audio_url = audio_url

    actions_summary = " | ".join(
        f"{u.action}:{u.exercise_match.exercise_name if u.exercise_match else u.spoken_exercise_name or '?'}"
        for u in result.updates
    )
    logger.info(
        "[WorkoutVoice] → RESPONSE voice | patient=%s | transcript=%r | updates=%d [%s] "
        "| response_exercises=%d [%s]",
        pid,
        result.transcript,
        len(result.updates),
        actions_summary,
        len(result.session.exercises),
        ", ".join(f"{e.exercise_name}({len(e.sets)}s)" for e in result.session.exercises),
    )

    return SuccessResponse(
        message="Voice input processed",
        data=result.model_dump(mode="json"),
    )


@router.post(
    "/{patient_id}/workouts/voice/text",
    response_model=SuccessResponse,
)
async def workout_text_input(
    patient_id: str,
    transcript: str = Form(..., description="Text description of the exercise/set."),
    session_state: str = Form(
        "{}",
        description="JSON-encoded WorkoutVoiceSessionState.",
    ),
    service: WorkoutVoiceService = Depends(get_workout_voice_service),
    current_actor: Actor = Depends(get_current_actor(**_ACTOR_DEPS)),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    """Same as voice endpoint but with text input — for typing or testing."""
    verified_pid = await resolve_patient_access(
        actor=current_actor,
        patient_id=UUID(patient_id),
        care_provider_access_service=care_provider_access_service,
    )

    if not transcript.strip():
        raise_http_exception(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="Transcript cannot be empty.",
        )

    try:
        session = WorkoutVoiceSessionState.model_validate_json(session_state)
    except Exception:
        raise_http_exception(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="Invalid session_state JSON.",
        )

    logger.info(
        "[WorkoutVoice] ← INCOMING text | patient=%s | transcript=%r | session_exercises=%d [%s]",
        str(verified_pid),
        transcript,
        len(session.exercises),
        ", ".join(f"{e.exercise_name}({len(e.sets)}s)" for e in session.exercises),
    )

    try:
        result = await service.process_text_input(
            transcript=transcript,
            session=session,
        )
    except Exception as exc:
        logger.error("Workout text processing failed: %s", exc)
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to process text input.",
            detail=str(exc),
        )

    actions_summary = " | ".join(
        f"{u.action}:{u.exercise_match.exercise_name if u.exercise_match else u.spoken_exercise_name or '?'}"
        for u in result.updates
    )
    logger.info(
        "[WorkoutVoice] → RESPONSE text | patient=%s | updates=%d [%s] "
        "| response_exercises=%d [%s]",
        str(verified_pid),
        len(result.updates),
        actions_summary,
        len(result.session.exercises),
        ", ".join(f"{e.exercise_name}({len(e.sets)}s)" for e in result.session.exercises),
    )

    return SuccessResponse(
        message="Text input processed",
        data=result.model_dump(mode="json"),
    )
