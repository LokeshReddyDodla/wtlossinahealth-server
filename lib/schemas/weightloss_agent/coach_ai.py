"""Schemas for AI-generated coach suggestion cards."""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


CoachCardTypeLiteral = Literal["nudge", "timer", "reminder", "meal", "pantry"]


class AiCoachSuggestionCard(BaseModel):
    card_type: CoachCardTypeLiteral
    title: str = Field(..., min_length=1, max_length=80)
    body: str = Field(..., min_length=1, max_length=400)
    cta: Optional[str] = Field(default=None, max_length=80)
    context_tags: List[str] = Field(default_factory=list)
    metric_ids: List[str] = Field(
        default_factory=list,
        description="Metric ids grounded in the provided plan snapshot.",
    )
    habit_ids: List[str] = Field(
        default_factory=list,
        description="Habit ids grounded in the provided plan snapshot.",
    )
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class AiCoachCardsResponse(BaseModel):
    cards: List[AiCoachSuggestionCard] = Field(default_factory=list)

