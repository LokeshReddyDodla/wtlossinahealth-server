from fastapi import Depends, HTTPException, Request, status

from lib.core.types import AiConversationTypeLiteral
from lib.dependencies.auth.patient_auth import get_current_patient
from lib.models.patient import Patient as PatientModel
from lib.services.ai_conversation_service.ai_conversation_service import \
    AiConversationService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.post("/respond", response_model=SuccessResponse)
async def send_ai_conversation_message(
    request: Request,
    conversation_id: str,
    human_input: str,
    conversation_type: AiConversationTypeLiteral,
    current_patient: PatientModel = Depends(get_current_patient),
):
    try:
        ai_conversation_service = AiConversationService(
            conversation_type=conversation_type,
            selected_ai_model="gemini-2.0-flash",
            ai_model_provider="gemini",
        )

        # Generate response from the AI model
        ai_message_data = await ai_conversation_service.generate_response(
            patient_id=str(current_patient.patient_id),
            conversation_id=conversation_id,
            conversation_type=conversation_type,
            human_input=human_input,
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
    current_patient: PatientModel = Depends(get_current_patient),
):
    """
    Get a personalized health tip of the day for the current patient.
    """
    try:
        ai_conversation_service = AiConversationService(
            conversation_type="health-tip",
            selected_ai_model="gpt-4o-mini",
            ai_model_provider="openai",
        )
        # Generate the health tip of the day
        health_tip = await ai_conversation_service.generate_health_tip_of_the_day(
            patient_id=str(current_patient.patient_id),
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
