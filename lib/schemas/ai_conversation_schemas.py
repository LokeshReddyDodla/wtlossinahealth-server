from datetime import datetime
from typing import Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from lib.core.constants import ProfileTypeEnum
from lib.core.types import (AiConversationMessageTypeLiteral,
                            AiConversationRoleLiteral,
                            AiConversationTypeLiteral)


class AIResponseFollowUpQuestions(BaseModel):
    questions: List[str] = Field(
        default=...,
        description="List of 3-5 relevant follow-up questions based on the AI response",
    )


class AiConversationMessage(BaseModel):
    user_id: str
    user_type: ProfileTypeEnum
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

    class Config:
        use_enum_values = True


class AIResponse(BaseModel):
    response: str = Field(
        ...,
        description="The AI's generated response, including embedded citations.",
    )
    # citations: Optional[List[Any]] = Field(
    #     default_factory=list,
    #     description="List of citations used in the response.",
    # )
    confidence_score: Optional[float] = Field(
        default=None,
        description="Confidence score of the AI's response (0 to 1).",
    )
    tags: Optional[List[str]] = Field(
        default=None,
        description="Tags/categories for the response (e.g., 'diet', 'exercise').",
    )
