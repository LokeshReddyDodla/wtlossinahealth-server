from fastapi import Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder

from lib.core.types import AiConversationTypeLiteral
from lib.dependencies.auth.base import get_current_user
from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.service_dependencies import get_ai_conversation_service
from lib.models.patient import Patient as PatientModel
from lib.services.ai_conversation_service import AiConversationService
from rest_server.response_models import SuccessResponse

from .router import router


@router.post("/respond", response_model=SuccessResponse)
async def send_ai_conversation_message(
    request: Request,
    conversation_type: AiConversationTypeLiteral,
    conversation_id: str,
    human_input: str,
    current_patient: PatientModel = Depends(get_current_patient),
):
    """
    Send a message to AI conversation and get a response.
    """
    try:
        ai_conversation_service = AiConversationService(
            conversation_type=conversation_type, model="gpt-4o-mini"
        )
        # Generate response from the AI model
        ai_response = await ai_conversation_service.generate_response(
            patient_id=str(current_patient.patient_id),
            conversation_id=conversation_id,
            human_input=human_input,
        )

        return SuccessResponse(
            message="AI response generated successfully.",
            data=ai_response,
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to generate response: {str(e)}"
        )
