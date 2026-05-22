"""Consultation service — orchestrates audio upload, STT, and structured extraction.

Storage layout:
- S3:    raw audio file
- Mongo: patient_consultations collection (transcript + extracted_data)
"""

from __future__ import annotations

import logging
import mimetypes
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from lib.ai_foundation.voice.stt import SpeechToText
from lib.core.mongo_store import MongoStore
from lib.schemas.consultation import (
    ConsultationListItem,
    ConsultationResponse,
    ExtractedConsultation,
)
from lib.services.consultation_extraction_service import (
    ConsultationExtractionService,
)
from lib.utils.s3_utils import upload_file_to_s3

logger = logging.getLogger(__name__)


_COLLECTION = "patient_consultations"
_S3_BUCKET = "user-assets.aihealth.clinic"

# Whisper-supported containers (verbose_json works for all of these).
_ALLOWED_AUDIO_MIME_PREFIXES = ("audio/", "video/webm", "video/mp4")
_EXT_BY_MIME = {
    "audio/webm": "webm",
    "audio/ogg": "ogg",
    "audio/mp4": "m4a",
    "audio/aac": "aac",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/wave": "wav",
    "video/webm": "webm",  # MediaRecorder on Chrome sometimes labels webm this way
    "video/mp4": "m4a",
}


class ConsultationService:
    def __init__(
        self,
        mongo_store: MongoStore,
        stt: SpeechToText,
        extraction_service: ConsultationExtractionService,
    ):
        self.mongo_store = mongo_store
        self.stt = stt
        self.extraction_service = extraction_service

    # ── Public API ──────────────────────────────────────────────────────

    async def create_from_audio(
        self,
        *,
        patient_id: str,
        audio_bytes: bytes,
        original_filename: str | None,
        mime_type: str | None,
        recorded_by_id: str,
        recorded_by_type: str,
    ) -> ConsultationResponse:
        """Upload audio → STT → extract → persist with one Mongo write."""
        consultation_id = str(uuid4())
        ext = _resolve_extension(mime_type, original_filename)
        s3_filename = f"audio.{ext}"

        # 1. Persist audio in S3 first so the recording survives any
        # downstream failure.
        audio_url = upload_file_to_s3(
            file_bytes=audio_bytes,
            bucket_name=_S3_BUCKET,
            file_name=s3_filename,
            content_type=mime_type or "audio/webm",
            folder_path=f"patients/{patient_id}/consultations/{consultation_id}",
        )
        if not audio_url:
            raise RuntimeError("Failed to upload consultation audio to S3")

        # 2. STT → 3. Extraction, all in memory.
        stt_result = await self.stt.transcribe_file(
            audio_bytes,
            filename=s3_filename,
        )
        transcript = stt_result.text or ""

        if transcript.strip():
            extracted = await self.extraction_service.extract(transcript)
        else:
            extracted = ExtractedConsultation()

        # 4. Single Mongo write — the row only exists once we have everything.
        now = _utcnow()
        doc: dict[str, Any] = {
            "consultation_id": consultation_id,
            "patient_id": patient_id,
            "audio_url": audio_url,
            "audio_duration_seconds": stt_result.duration_seconds,
            "transcript": transcript,
            "extracted_data": extracted.model_dump(mode="json"),
            "status": "draft",
            "recorded_by_id": recorded_by_id,
            "recorded_by_type": recorded_by_type,
            "recorded_at": now,
            "created_at": now,
            "updated_at": now,
        }
        await self.mongo_store.insert_document(_COLLECTION, doc)

        return ConsultationResponse(
            consultation_id=consultation_id,
            patient_id=patient_id,
            audio_url=audio_url,
            audio_duration_seconds=stt_result.duration_seconds,
            transcript=transcript,
            extracted_data=extracted,
            status="draft",
            recorded_by_id=recorded_by_id,
            recorded_by_type=recorded_by_type,
            recorded_at=now,
            created_at=now,
            updated_at=now,
        )

    async def list_for_patient(
        self,
        patient_id: str,
    ) -> list[ConsultationListItem]:
        docs = await self.mongo_store.find_many(
            _COLLECTION,
            {"patient_id": patient_id},
            projection={
                "_id": 0,
                "consultation_id": 1,
                "patient_id": 1,
                "audio_duration_seconds": 1,
                "status": 1,
                "extracted_data.chief_complaint": 1,
                "extracted_data.summary": 1,
                "recorded_by_id": 1,
                "recorded_by_type": 1,
                "recorded_at": 1,
                "created_at": 1,
            },
        )
        docs.sort(key=lambda d: d.get("recorded_at") or d.get("created_at"), reverse=True)
        return [_to_list_item(d) for d in docs]

    async def get(
        self,
        *,
        patient_id: str,
        consultation_id: str,
    ) -> ConsultationResponse | None:
        doc = await self.mongo_store.find_document(
            _COLLECTION,
            {"consultation_id": consultation_id, "patient_id": patient_id},
        )
        if not doc:
            return None
        return _to_response(doc)

# ── Helpers ─────────────────────────────────────────────────────────────


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _resolve_extension(mime_type: str | None, filename: str | None) -> str:
    if mime_type and mime_type in _EXT_BY_MIME:
        return _EXT_BY_MIME[mime_type]
    if filename and "." in filename:
        ext = filename.rsplit(".", 1)[-1].lower()
        if ext:
            return ext
    if mime_type:
        guessed = mimetypes.guess_extension(mime_type)
        if guessed:
            return guessed.lstrip(".")
    return "webm"


def is_supported_audio_mime(mime_type: str | None) -> bool:
    if not mime_type:
        return False
    return any(mime_type.startswith(prefix) for prefix in _ALLOWED_AUDIO_MIME_PREFIXES)


def _to_response(doc: dict) -> ConsultationResponse:
    extracted_raw = doc.get("extracted_data")
    extracted = (
        ExtractedConsultation.model_validate(extracted_raw) if extracted_raw else None
    )
    return ConsultationResponse(
        consultation_id=doc["consultation_id"],
        patient_id=doc["patient_id"],
        audio_url=doc["audio_url"],
        audio_duration_seconds=doc.get("audio_duration_seconds"),
        transcript=doc.get("transcript"),
        extracted_data=extracted,
        status=doc["status"],
        recorded_by_id=doc["recorded_by_id"],
        recorded_by_type=doc["recorded_by_type"],
        recorded_at=doc["recorded_at"],
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )


def _to_list_item(doc: dict) -> ConsultationListItem:
    extracted = doc.get("extracted_data") or {}
    return ConsultationListItem(
        consultation_id=doc["consultation_id"],
        patient_id=doc["patient_id"],
        audio_duration_seconds=doc.get("audio_duration_seconds"),
        status=doc["status"],
        chief_complaint=extracted.get("chief_complaint"),
        summary=extracted.get("summary"),
        recorded_by_id=doc["recorded_by_id"],
        recorded_by_type=doc["recorded_by_type"],
        recorded_at=doc["recorded_at"],
        created_at=doc["created_at"],
    )
