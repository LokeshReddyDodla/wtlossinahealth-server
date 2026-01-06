"""Schemas for AI-generated plan composer output."""

from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class AiPlanMetricRange(BaseModel):
    min_value: Optional[float] = None
    max_value: Optional[float] = None


class AiPlanComposerResponse(BaseModel):
    """
    AI output used to build a PlanSnapshot. We keep it minimal so the server remains
    the source of truth for labels/units/cadence/sources.
    """

    targets: Dict[str, AiPlanMetricRange] = Field(default_factory=dict)
    hydration_oz: AiPlanMetricRange = Field(default_factory=AiPlanMetricRange)
    habits: List[str] = Field(default_factory=list, description="Habit descriptions")

