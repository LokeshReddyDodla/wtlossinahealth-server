from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class QueryResponse(BaseModel):
    type: str = "response"
    is_ready: bool
    user_message: str
    message_count: int
    turn_number: int
    message: str
    data_types: Optional[List[str]] = None
    date_range: Optional[dict] = None
    hour_range: Optional[dict] = None
    month_filters: Optional[List[int]] = None
    time_buckets: Optional[List[str]] = None
    final_response: Optional[str] = None
    clarification_msg: Optional[str] = None
    suggestions: Optional[List[dict]] = None
    confidence: Optional[float] = Field(
        None, description="Intent extraction confidence score (0.0-1.0), for debugging."
    )
    search_confidence: Optional[float] = Field(
        None, description="Top search result similarity score (0.0-1.0), for debugging."
    )


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
