import json
from datetime import datetime
from email import message
from typing import Dict, Optional, Union
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from lib.core.auth_bearer import handler
from lib.managers.context_manager import context_manager
from lib.utils.context_utils import identify_context
from lib.utils.json_parsing import parse_json_garbage
from lib.utils.openai.meal_analysis import get_nutritional_info
from rest_server.chat.api_scheme import ChatRequest, ChatResponse
from rest_server.meals.api_schema import MealDescription
from rest_server.response_models import ErrorResponse, SuccessResponse
from services.chat_handler import chat_handler

# Create FastAPI router
router = APIRouter(prefix="/chat")

    
@router.post(path="/",  tags=["Chat"])
async def default_chat(
    request: Request,
    body: ChatRequest,
    # user=handler,
) -> Union[ChatResponse, HTTPException]:
    try:
        # Identify context and create a new context window if necessary
        document_type = body.document_type or "general"
        context_id = uuid.uuid4().hex
        print(f"==> context_id: {context_id}")
        
        context_manager.create_context(context_id, document_type)
        
        # Add message to context
        context_manager.add_message(context_id, body.message, "user")
        
        # Get relevant conversation window
        context = identify_context(document_type)
        context_window = context_manager.get_context_window(context_id)
        
        # Chat with user
        result = chat_handler(body.message, context_window)
        
        return ChatResponse(content=result, context_id=context_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))