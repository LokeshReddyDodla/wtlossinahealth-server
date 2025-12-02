"""Suggestion card schemas used by the coach messenger."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class CoachActionRequest(BaseModel):
    user_id: UUID
    context_tags: List[str] = Field(default_factory=list)
    trigger: str = Field(
        ..., description="user action that triggered the coaching card"
    )
    plan_id: Optional[UUID] = None


class SuggestionCard(BaseModel):
    card_id: UUID
    user_id: UUID
    card_type: str = Field(
        ..., description="nudge | timer | meal | pantry | reminder"
    )
    title: str
    body: str
    cta: Optional[str] = None
    context_tags: List[str] = Field(default_factory=list)
    sources: List[str] = Field(default_factory=list)
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    abstained: bool = False
    abstain_reason: Optional[str] = None
    created_at: datetime
    provenance: dict = Field(default_factory=dict)


class CoachActionResponse(BaseModel):
    cards: List[SuggestionCard] = Field(default_factory=list)
    abstained: bool = False
    reason: Optional[str] = None
