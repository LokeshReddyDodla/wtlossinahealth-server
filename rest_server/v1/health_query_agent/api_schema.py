import json as _json

from pydantic import BaseModel, Field, field_validator
from typing import Any, Optional
from datetime import datetime


class QueryRequest(BaseModel):
    message: str = Field(
        ..., description="The user's query message", min_length=1, max_length=5000
    )
    patient_ids: Optional[list[str]] = Field(
        None, description="Optional list of patient IDs to filter search results"
    )
    tier: Optional[str] = Field(
        None, description="Reasoning tier: basic, standard, advanced, unlimited. Defaults to config.",
    )
    metadata: Optional[dict[str, Any]] = Field(
        None, description="Optional context — e.g. insight_id from a notification tap.",
    )
    local_time: Optional[str] = Field(
        None, description="Device local time as ISO string (e.g. '2026-03-28T14:27:00+05:30'). Used for resolving 'today', 'yesterday', etc.",
    )

    @field_validator("message")
    @classmethod
    def validate_message(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Message cannot be empty")
        return v.strip()

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        if v is None:
            return v
        if len(v) > 10:
            raise ValueError("metadata must have at most 10 keys")
        if len(_json.dumps(v, default=str)) > 2048:
            raise ValueError("metadata payload too large (max 2 KB)")
        return v


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
