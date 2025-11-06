from typing import List, Optional
from fastapi import Depends, HTTPException, Request, status
from lib.dependencies.auth.care_provider_auth import get_current_care_provider
from lib.dependencies.service_dependencies import (
    get_ai_conversation_service_v1,
)
from lib.services.ai_conversation_service_v1.ai_conversation_service_v1 import (
    AIConversationServiceV1,
)
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse
from .router import router


@router.post("/ask", response_model=SuccessResponse)
async def ask_ai_in_careprovider_conversation(
    request: Request,
    patient_ids: List[str],
    conversation_id: str,
    human_input: str,
    report_id: Optional[str] = None,
    ai_conversation_service_v1: AIConversationServiceV1 = Depends(
        get_ai_conversation_service_v1
    ),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.CREATE,
            CareProviderFeature.AI_CHATS,
        )
    ),
):
    try:
        ai_message_data = await ai_conversation_service_v1.generate_response(
            patient_ids=patient_ids,
            sender_id=str(current_care_provider.care_provider_id),
            report_id=report_id,
            sender_type="care_provider",
            conversation_id=conversation_id,
            human_input=human_input,
            api_endpoint=request.url.path,
        )

        return SuccessResponse(
            message="AI conversation response generated successfully.",
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
