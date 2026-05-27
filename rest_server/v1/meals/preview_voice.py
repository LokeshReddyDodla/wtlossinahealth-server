"""Meal voice preview endpoints — full analysis and quick (nutrition-only).

Multipart siblings of the JSON preview endpoints. The server uploads
the audio to S3 (for archival), transcribes it via Whisper, and feeds
the transcript into the MealAnalysisAgent pipeline.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import Depends, File, Form, UploadFile, status
from fastapi.exceptions import HTTPException

from lib.ai_foundation.agents.meal_analysis.agent import MealAnalysisAgent
from lib.ai_foundation.voice.stt import SpeechToText
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
from rest_server.response_models import SuccessResponse

from ._audio import process_audio
from .router import router

_PREVIEW_DEPS = dict(
    allowed_roles=[
        ProfileTypeEnum.ADMIN,
        ProfileTypeEnum.CARE_PROVIDER,
        ProfileTypeEnum.PATIENT,
    ],
    care_provider_feature=CareProviderFeature.MEALS,
    care_provider_action=CareProviderPermissionAction.READ,
)


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
    current_actor: Actor = Depends(get_current_actor(**_PREVIEW_DEPS)),
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

    audio_url, combined_text = await process_audio(
        audio=audio, stt=stt, patient_id=pid, text=text,
    )

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
                "transcript": combined_text,
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


@router.post(
    "/{patient_id}/quick-preview/voice",
    response_model=SuccessResponse,
)
async def quick_preview_meal_voice(
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
    current_actor: Actor = Depends(get_current_actor(**_PREVIEW_DEPS)),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    """Extract nutrition from audio input. No scoring or insights, no DB write."""
    verified_pid = await resolve_patient_access(
        actor=current_actor,
        patient_id=UUID(patient_id),
        care_provider_access_service=care_provider_access_service,
    )
    pid = str(verified_pid)

    audio_url, combined_text = await process_audio(
        audio=audio, stt=stt, patient_id=pid, text=text,
    )

    request = MealPreviewRequest(
        slot=slot,
        source=source,
        consumed_at=consumed_at,
        image_url=image_url,
        text=combined_text,
        portion_note=portion_note,
    )

    try:
        result = await agent.quick_analyze(patient_id=pid, request=request)
        return SuccessResponse(
            message="Meal extracted",
            data={
                **result.model_dump(mode="json"),
                "audio_url": audio_url,
                "transcript": combined_text,
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
            message="Failed to extract meal nutrition. Please try again.",
            detail=str(exc),
        )
