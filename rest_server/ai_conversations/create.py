from fastapi import Depends, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy.ext.asyncio import AsyncSession

from lib.core.types import AiConversationTypeLiteral
from lib.dependencies.auth.base import get_current_user
from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.database import get_postgres_session
from lib.dependencies.service_dependencies import (get_ai_conversation_service,
                                                   get_patient_profile_service)
from lib.models.patient import Patient as PatientModel
from lib.services.ai_conversation_service import AiConversationService
from lib.services.patient_profile_service import PatientProfileService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.post("/respond", response_model=SuccessResponse)
async def send_ai_conversation_message(
    request: Request,
    conversation_id: str,
    human_input: str,
    conversation_type: AiConversationTypeLiteral,
    patient_profile_service: PatientProfileService = Depends(
        get_patient_profile_service
    ),
    current_patient: PatientModel = Depends(get_current_patient),
):
    """
    Send a message to AI conversation and get a response.
    """
    try:
        ai_conversation_service = AiConversationService(
            conversation_type=conversation_type,
            model="gpt-4o-mini",
        )
        # Generate response from the AI model
        ai_message_data = await ai_conversation_service.generate_response(
            patient_id=str(current_patient.patient_id),
            conversation_id=conversation_id,
            conversation_type=conversation_type,
            human_input=human_input,
            patient_profile_service=patient_profile_service,
        )

        return SuccessResponse(
            message="AI response generated successfully.",
            data=ai_message_data,
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to generate AI response.",
            detail=str(e),
        )


@router.post("/health-tip", response_model=SuccessResponse)
async def get_daily_health_tip(
    request: Request,
    patient_profile_service: PatientProfileService = Depends(
        get_patient_profile_service
    ),
    current_patient: PatientModel = Depends(get_current_patient),
):
    """
    Get a personalized health tip of the day for the current patient.
    """
    try:
        ai_conversation_service = AiConversationService(
            conversation_type="health-tip",
            model="gpt-4o-mini",
        )
        # Generate the health tip of the day
        health_tip = (
            await ai_conversation_service.generate_health_tip_of_the_day(
                patient_id=str(current_patient.patient_id),
                patient_profile_service=patient_profile_service,
            )
        )

        return SuccessResponse(
            message="Health tip of the day generated successfully.",
            data=health_tip,
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to generate health tip of the day.",
            detail=str(e),
        )
