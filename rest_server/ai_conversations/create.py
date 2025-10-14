from typing import Any, Optional
from fastapi import Body, Depends, HTTPException, Request, status

from lib.core.constants import ProfileTypeEnum
from lib.core.types import AiConversationTypeLiteral
from lib.dependencies.auth.care_provider_auth import get_current_care_provider
from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.service_dependencies import get_qdrant_search_engine
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.models.patient import Patient as PatientModel
from lib.services.ai_conversation_service.ai_conversation_service import (
    AiConversationService,
)
from lib.services.ai_conversation_service.ai_conversation_service_v2 import (
    AiConversationServiceV2,
)
from lib.services.qdrant_search_engine.qdrant_search_engine import (
    QdrantSearchEngine,
)
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.post("/patient/respond", response_model=SuccessResponse)
async def send_ai_conversation_patient_message(
    request: Request,
    conversation_id: str,
    human_input: str,
    conversation_type: AiConversationTypeLiteral,
    current_patient: PatientModel = Depends(get_current_patient),
):
    try:
        ai_conversation_service = AiConversationService(
            conversation_type=conversation_type,
            selected_ai_model="gpt-4.1-mini",  # sonar
            ai_model_provider="openai",  # perplexity
        )

        # Generate response from the AI model
        ai_message_data = await ai_conversation_service.generate_response(
            user_id=str(current_patient.patient_id),
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


@router.post("/care-provider/respond", response_model=SuccessResponse)
async def send_ai_conversation_careprovider_message(
    request: Request,
    patient_id: str,
    conversation_id: str,
    human_input: str,
    conversation_type: AiConversationTypeLiteral,
    additional_context: Optional[Any] = Body(None),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.CREATE,
            CareProviderFeature.AI_CHATS,
        )
    ),
):
    try:
        ai_conversation_service = AiConversationService(
            conversation_type=conversation_type,
            selected_ai_model="gpt-4o-mini",
            ai_model_provider="openai",
        )

        # Generate response from the AI model
        ai_message_data = await ai_conversation_service.generate_response(
            user_id=str(current_care_provider.care_provider_id),
            patient_id=patient_id,
            conversation_id=conversation_id,
            conversation_type=conversation_type,
            human_input=human_input,
            additional_context=additional_context,
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


@router.post("/care-provider/respond/v2", response_model=SuccessResponse)
async def send_ai_conversation_careprovider_message(
    request: Request,
    patient_id: str,
    conversation_id: str,
    human_input: str,
    qdrant_service_engine: QdrantSearchEngine = Depends(
        get_qdrant_search_engine
    ),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.CREATE,
            CareProviderFeature.AI_CHATS,
        )
    ),
):
    try:
        ai_conversation_service = AiConversationServiceV2(
            qdrant_search_engine=qdrant_service_engine,
            selected_ai_model="gpt-4o-mini",
            ai_model_provider="openai",
        )

        # Generate response from the AI model
        ai_message_data = await ai_conversation_service.generate_response(
            patient_id=patient_id,
            user_id=str(current_care_provider.care_provider_id),
            user_type=ProfileTypeEnum.CARE_PROVIDER,
            conversation_id=conversation_id,
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


@router.post("/patient/health-tip", response_model=SuccessResponse)
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
        health_tip = (
            await ai_conversation_service.generate_health_tip_for_patient(
                patient_id=str(current_patient.patient_id),
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
