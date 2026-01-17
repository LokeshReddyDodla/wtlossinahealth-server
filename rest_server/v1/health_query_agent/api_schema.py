from pydantic import BaseModel, Field, field_validator
from typing import Optional
from datetime import datetime


class QueryRequest(BaseModel):
    message: str = Field(
        ..., description="The user's query message", min_length=1, max_length=5000
    )
    patient_ids: Optional[list[str]] = Field(
        None, description="Optional list of patient IDs to filter search results"
    )

    @field_validator("message")
    @classmethod
    def validate_message(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Message cannot be empty")
        return v.strip()


class ConversationMessage(BaseModel):
    message_type: str = Field(..., description="'user' or 'assistant'")
    content: str = Field(..., description="Message content")
    timestamp: datetime = Field(..., description="Message timestamp")
    intent: Optional[dict] = Field(
        None, description="Intent data (for assistant messages)"
    )
    response: Optional[dict] = Field(
        None, description="Response data (for assistant messages)"
    )
    metadata: Optional[dict] = Field(None, description="Additional metadata")


class ConversationHistoryResponse(BaseModel):
    user_id: str = Field(..., description="User ID")
    total_messages: int = Field(..., description="Total number of messages")
    messages: list[ConversationMessage] = Field(..., description="List of messages")
