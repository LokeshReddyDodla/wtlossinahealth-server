from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Union
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
    reply_suggestions: Optional[List[str]] = None  # follow_up_questions
    metadata: Optional[Dict] = None
    language: Optional[str] = "unknown"


class AIResponse(BaseModel):
    response: str = Field(
        ...,
        description="The AI's generated response, including embedded citations.",
    )
    # citations: Optional[List[Any]] = Field(
    #     default_factory=list,
    #     description="List of citations used in the response.",
    # )
    follow_up_questions: Optional[List[str]] = Field(
        default=None,
        description="List of follow-up questions or related queries the user might ask after this response.",
    )
    confidence_score: Optional[float] = Field(
        default=None,
        description="Confidence score of the AI's response (0 to 1).",
    )
    tags: Optional[List[str]] = Field(
        default=None,
        description="Tags/categories for the response (e.g., 'diet', 'exercise').",
    )
