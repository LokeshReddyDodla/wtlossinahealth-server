from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


# --- Enums ---
SenderTypeLiteral = Literal["patient", "care_provider", "ai", "system"]
RoleLiteral = Literal["human", "ai", "system"]
MessageTypeLiteral = Literal["text", "markdown", "json", "url", "error"]
MessageStatusLiteral = Literal["pending", "success", "failed"]


class AiConversationMessageV1(BaseModel):
    # --- Core IDs ---
    id: str = Field(default_factory=lambda: str(uuid4()))
    conversation_id: str
    conversation_type: str  # e.g. "meal", "smbg", "care_provider", etc.

    # --- Sender Info ---
    sender_id: str
    sender_type: SenderTypeLiteral  # patient, care_provider, ai, system
    role: RoleLiteral  # LLM role mapping

    # --- Message Content ---
    content: str  # actual message text or serialized JSON
    message_type: MessageTypeLiteral = "text"

    # --- State / Tracking ---
    status: MessageStatusLiteral = "success"
    error_message: Optional[str] = None
    model: Optional[str] = None  # e.g. "gpt-4o-mini"
    token_usage: Optional[Dict[str, int]] = (
        None  # {"prompt": 123, "completion": 456}
    )
    latency_ms: Optional[int] = None  # for monitoring response speed

    # --- Frontend / UX ---
    hidden_from_ui: bool = (
        False  # renamed from exclude_from_frontend (clearer meaning)
    )
    follow_up_questions: Optional[List[str]] = None

    # --- Extra Metadata ---
    metadata: Optional[Dict[str, Any]] = None
    language: Optional[str] = "unknown"
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        use_enum_values = True
