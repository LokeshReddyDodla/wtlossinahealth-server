import logging
import openai
from decouple import config
from lib.utils.retry_utils import retry_request
from lib.managers.context_manager import context_manager
from services.meal_handler import handle_meal_context
from services.report_handler import handle_report_context

logger = logging.getLogger(__name__)

def chat_handler(message: str, context_window: dict, is_contextual:bool = False) -> str:
    context_type = context_window.get("type")
    history = context_window.get("history", [])
    context_id = context_window.get("id")
    
    if context_id is None:
        raise ValueError("Context ID cannot be None")
    
    if context_type == "meal":
        return handle_meal_context(message, history, context_id, is_contextual=is_contextual)
    elif context_type == "report":
        return handle_report_context(message, history, context_id)
    else:
        raise ValueError(f"Unsupported context type: {context_type}")
