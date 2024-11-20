from datetime import datetime
from typing import List, Literal, Optional, Union
from uuid import uuid4

from pydantic import BaseModel, Field, constr

from lib.core.types import (AiConversationMessageTypeLiteral,
                            AiConversationRoleLiteral,
                            AiConversationTypeLiteral)


class AiResponseSuggestions(BaseModel):
    suggestions: List[str] = Field(
        description="List of suggested follow-up questions or replies for the user."
    )


class AiConversationMessage(BaseModel):
    patient_id: str
    message_id: str = Field(default_factory=lambda: str(uuid4()))
    conversation_id: str
    conversation_type: AiConversationTypeLiteral
    role: AiConversationRoleLiteral
    content: str
    timestamp: datetime = Field(default_factory=datetime.now)
    message_type: AiConversationMessageTypeLiteral
    exclude_from_frontend: bool = False
    reply_suggestions: Optional[List[str]] = None
