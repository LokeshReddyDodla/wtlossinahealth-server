from typing import Optional
from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    document_type: Optional[str] = None
    
class ContextChatRequest(BaseModel):
    context_id: str
    message: str
    
class ChatResponse(BaseModel):
    content: str
    context_id: Optional[str] = None