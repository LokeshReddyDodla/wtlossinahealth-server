from datetime import datetime
from typing import Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator

from lib.ai_foundation.agents.support_assistant.contracts import (
    HandlingMode,
    SupportCategory,
    SupportUrgency,
)
from lib.core.types import (
    SupportScopeLiteral,
    SupportTicketStatusLiteral,
)
from lib.schemas.chat_message import MediaSchema

RequesterTypeLiteral = Literal["patient", "care_provider"]


class SupportAssistantTicketState(BaseModel):
    """What the AI support assistant last concluded about this ticket.
    Written only by ``SupportAssistantService`` (``$set`` on ``assistant.*``);
    read by the staff queue for triage. Absent on tickets the bot never
    touched (care-provider tickets, bot disabled, human already engaged)."""

    category: Optional[SupportCategory] = None
    urgency: Optional[SupportUrgency] = None
    needs_human: bool = False
    summary: Optional[str] = None
    handling_mode: Optional[HandlingMode] = None
    reply_count: int = 0
    last_replied_at: Optional[datetime] = None
    last_trace_id: Optional[str] = None


class SupportTicketSchema(BaseModel):
    """Ticketing metadata for a support conversation. The actual messages
    live in the underlying chat (``chat_id``) so all chat infrastructure
    (Socket.IO, FCM, attachments, read receipts) is reused."""

    id: str = Field(
        default_factory=lambda: str(uuid4()),
        alias="_id",
    )
    chat_id: str
    scope: SupportScopeLiteral
    requester_id: str
    requester_type: RequesterTypeLiteral

    health_facility_id: Optional[str] = None
    subject: Optional[str] = None
    status: SupportTicketStatusLiteral = "open"

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    last_message_at: datetime = Field(default_factory=datetime.utcnow)
    last_message_preview: Optional[str] = None

    resolved_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None

    assistant: Optional[SupportAssistantTicketState] = None

    class Config:
        populate_by_name = True


class SupportTicketOpenRequest(BaseModel):
    scope: SupportScopeLiteral
    initial_message: str = Field(..., min_length=1, max_length=4000)
    subject: Optional[str] = Field(None, max_length=200)
    media: Optional[MediaSchema] = None
    health_facility_id: Optional[str] = None

    @model_validator(mode="after")
    def _facility_scope_requires_facility_id(self) -> "SupportTicketOpenRequest":
        if self.scope == "facility" and not self.health_facility_id:
            raise ValueError(
                "health_facility_id is required when scope == 'facility'"
            )
        return self


class SupportTicketStatusUpdateRequest(BaseModel):
    status: SupportTicketStatusLiteral


class SupportAgentReplyRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=4000)
    media: Optional[MediaSchema] = None
