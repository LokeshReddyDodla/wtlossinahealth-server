import json
from datetime import datetime
from email import message
import traceback
from typing import Dict, Optional, Union

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from lib.core.auth_bearer import handler
from lib.utils.json_parsing import parse_json_garbage
from lib.utils.openai.meal_analysis import get_nutritional_info
from rest_server.chat.api_scheme import ChatResponse, ContextChatRequest
from rest_server.meals.api_schema import FoodDescription, MealAnalysisResponse
from rest_server.response_models import ErrorResponse, SuccessResponse
from lib.managers.context_manager import context_manager
from lib.utils.context_utils import identify_context
from services.chat_handler import chat_handler

# Create FastAPI router
router = APIRouter(prefix="/chat")

    
@router.post(path="/context",  tags=["Chat"])
async def context_chat(
    request: Request,
    body: ContextChatRequest,
    # user=handler,
) -> Union[ChatResponse, HTTPException]:
    try:
        print("==> Context chat request")
        # Ensure context exists
        context_id = body.context_id
        print("==> context_id: %s" % context_id)
        print("==> context: ", context_manager.contexts)
        
        if context_id not in context_manager.contexts:
            raise HTTPException(status_code=404, detail="Context not found")

        # Add message to context
        context_manager.add_message(context_id, body.message, "user")
        
        # Get relevant conversation window
        context_window = context_manager.get_context_window(context_id)
        
        # Chat with user
        result = chat_handler(body.message, context_window)
        
        return ChatResponse(content=result, context_id=context_id)
    except Exception as e:
        error_message = f"Exception occurred: {str(e)}"
        traceback_message = traceback.format_exc()
        print(error_message)
        print(traceback_message)
        
        raise HTTPException(status_code=500, detail=str(e))