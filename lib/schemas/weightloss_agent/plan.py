"""Plan snapshot schemas for the weightloss agent composer output."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class PlanMetricRange(BaseModel):
    metric_id: str
    label: str
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    units: str
    cadence: str = Field("daily", description="daily or weekly cadence")
    sources: List[str] = Field(default_factory=list)


class HabitFocus(BaseModel):
    habit_id: str
    description: str
    cue: str
    measurement: str
    sources: List[str] = Field(default_factory=list)
    priority: int = 1


class SafetyRuleCap(BaseModel):
    rule_id: str
    action: str
    rationale_ids: List[str] = Field(default_factory=list)
    severity: str
    cap_value: Optional[float] = None
    units: Optional[str] = None


class PlanSnapshot(BaseModel):
    plan_id: UUID
    user_id: UUID
    generated_at: datetime
    review_after_days: int = 7
    valid_from: date
    valid_to: date
    targets: Dict[str, PlanMetricRange] = Field(default_factory=dict)
    hydration: PlanMetricRange
    habits_focus: List[HabitFocus] = Field(default_factory=list)
    safety_rules: List[SafetyRuleCap] = Field(default_factory=list)
    sources: List[str] = Field(default_factory=list)
    provenance: Dict[str, str] = Field(default_factory=dict)
    abstained: bool = False
    abstain_reason: Optional[str] = None


class PlanGenerateRequest(BaseModel):
    user_id: UUID
    enrollment_id: Optional[UUID] = None
    include_context: bool = True


class PlanGenerateResponse(BaseModel):
    plan_snapshot: Optional[PlanSnapshot] = None
    abstained: bool = False
    reason: Optional[str] = None
    ai_recommendations: Optional[Dict[str, Any]] = None
