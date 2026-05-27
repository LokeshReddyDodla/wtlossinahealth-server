"""Shared audio handling for meal voice endpoints."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile, status

from lib.ai_foundation.voice.config import voice_settings
from lib.ai_foundation.voice.stt import AudioFormat, SpeechToText
from lib.utils.http_exceptions import raise_http_exception
from lib.utils.s3_utils import upload_file_to_s3

logger = logging.getLogger(__name__)

S3_BUCKET = "user-assets.aihealth.clinic"

_MEAL_STT_PROMPT = (
    "A person describing what they ate or are about to eat — "
    "food items, portion sizes, and meal context."
)

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


def sniff_audio_format(upload: UploadFile) -> AudioFormat | None:
    if upload.content_type:
        fmt = _FORMAT_BY_MIME.get(upload.content_type.lower())
        if fmt is not None:
            return fmt
    if upload.filename:
        return _FORMAT_BY_EXTENSION.get(Path(upload.filename).suffix.lower())
    return None


async def process_audio(
    *,
    audio: UploadFile,
    stt: SpeechToText,
    patient_id: str,
    text: str | None = None,
) -> tuple[str | None, str]:
    """Validate, upload to S3, transcribe, and return (audio_url, combined_text).

    Raises HTTP exceptions on validation or transcription failure.
    """
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

    audio_format = sniff_audio_format(audio)
    if audio_format is None:
        raise_http_exception(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            message=f"Unsupported audio format: {audio.content_type or audio.filename!r}.",
        )

    s3_task = asyncio.to_thread(
        upload_file_to_s3,
        file_bytes=audio_bytes,
        bucket_name=S3_BUCKET,
        file_name=f"{uuid4()}.{audio_format}",
        content_type=audio.content_type or f"audio/{audio_format}",
        folder_path=f"patients/{patient_id}/meals/audio",
    )
    stt_task = stt.transcribe(audio_bytes, audio_format=audio_format, prompt=_MEAL_STT_PROMPT)

    audio_url, transcript = await asyncio.gather(s3_task, stt_task, return_exceptions=True)

    if isinstance(transcript, Exception):
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to transcribe audio.",
            detail=str(transcript),
        )
    if isinstance(audio_url, Exception):
        logger.warning("S3 audio upload failed for patient %s: %s", patient_id, audio_url)
        audio_url = None

    if not transcript.text.strip():
        raise_http_exception(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            message="Could not understand the audio. Please try again.",
        )

    combined_text = f"{text} {transcript.text}" if text else transcript.text
    return audio_url, combined_text
