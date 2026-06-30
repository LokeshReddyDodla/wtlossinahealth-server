"""Request/response schemas for the Dashboard Help (helpline) endpoint."""

from __future__ import annotations

from pydantic import BaseModel, Field


class HistoryTurn(BaseModel):
    role: str = Field(..., description="'user' or 'assistant'.")
    content: str


class DashboardHelpRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000, description="The user's question.")
    history: list[HistoryTurn] = Field(
        default_factory=list,
        description="Prior turns of this conversation, oldest first.",
    )


class DashboardHelpResponse(BaseModel):
    reply: str = Field(description="Step-by-step answer.")
    video_url: str | None = Field(default=None, description="Matching how-to video URL, if any.")
    video_id: str | None = Field(default=None, description="Matching video id, if any.")
    trace_id: str | None = None
