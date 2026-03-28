"""
Proactive Monitor Contracts — schemas for insights, scan results, and
notification payloads.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class InsightSeverity(str, Enum):
    """How urgent the insight is."""

    INFO = "info"           # positive reinforcement, FYI
    ATTENTION = "attention"  # worth noting, not urgent
    WARNING = "warning"      # needs attention soon
    ALERT = "alert"          # needs immediate attention


SEVERITY_RANK: dict[str, int] = {
    "info": 1,
    "attention": 2,
    "warning": 3,
    "alert": 4,
}


class InsightCategory(str, Enum):
    """What kind of insight this is."""

    # Concerns (LLM-generated)
    GLUCOSE_SPIKE = "glucose_spike"
    GLUCOSE_HYPO = "glucose_hypo"
    GLUCOSE_RAPID_SPIKE = "glucose_rapid_spike"
    GLUCOSE_RAPID_DROP = "glucose_rapid_drop"
    GLUCOSE_WORSENING = "glucose_worsening"
    MEAL_HIGH_CARB = "meal_high_carb"
    MEAL_LOW_PROTEIN = "meal_low_protein"
    FITNESS_INACTIVE = "fitness_inactive"
    SLEEP_POOR = "sleep_poor"

    # Positives (LLM-generated)
    GLUCOSE_IMPROVING = "glucose_improving"
    FITNESS_STREAK = "fitness_streak"
    SLEEP_IMPROVING = "sleep_improving"
    GOAL_PROGRESS = "goal_progress"

    # Static only (generated without LLM, never by LLM)
    MEAL_MISSED = "meal_missed"
    ENGAGEMENT_DROP = "engagement_drop"

    # Neutral
    GENERAL = "general"


# Categories the LLM can pick from (excludes static-only ones)
_CONCERN_CATEGORIES = [
    InsightCategory.GLUCOSE_SPIKE, InsightCategory.GLUCOSE_HYPO,
    InsightCategory.GLUCOSE_RAPID_SPIKE, InsightCategory.GLUCOSE_RAPID_DROP,
    InsightCategory.GLUCOSE_WORSENING, InsightCategory.MEAL_HIGH_CARB,
    InsightCategory.MEAL_LOW_PROTEIN, InsightCategory.FITNESS_INACTIVE,
    InsightCategory.SLEEP_POOR,
]
_POSITIVE_CATEGORIES = [
    InsightCategory.GLUCOSE_IMPROVING, InsightCategory.FITNESS_STREAK,
    InsightCategory.SLEEP_IMPROVING, InsightCategory.GOAL_PROGRESS,
]

LLM_INSIGHT_CATEGORIES_PROMPT = (
    "CATEGORIES — pick the one that fits best:\n"
    f"Concerns: {', '.join(c.value for c in _CONCERN_CATEGORIES)}\n"
    f"Positives: {', '.join(c.value for c in _POSITIVE_CATEGORIES)}\n"
    "Neutral: general"
)


class HealthInsight(BaseModel):
    """A single insight detected by the proactive monitor."""

    insight_id: str = Field(default_factory=lambda: f"ins_{uuid4().hex[:12]}")
    category: InsightCategory
    severity: InsightSeverity
    title: str = Field(max_length=50, description="Push notification title. Max 50 characters.")
    body: str = Field(max_length=200, description="Push notification body. Max 200 characters.")
    patient_id: str = ""
    data: dict[str, Any] = Field(
        default_factory=dict,
        description="Supporting data (metrics, comparisons, etc.).",
    )
    actionable: bool = Field(
        default=True,
        description="Whether the insight has a concrete action the patient can take.",
    )
    suggested_query: str | None = Field(
        default=None,
        description="A query the patient could ask the health agent for more details.",
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ScanInsights(BaseModel):
    """Structured extraction model for multiple insights from a scan."""

    insights: list[HealthInsight] = Field(
        default_factory=list,
        description="List of noteworthy health insights found during the scan.",
    )


class ScanResult(BaseModel):
    """Result from scanning a single patient."""

    patient_id: str
    scan_date: str = ""
    insights: list[HealthInsight] = Field(default_factory=list)
    scanned_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    scan_duration_ms: int = 0
    data_available: bool = True
    error: str | None = None

    @property
    def has_insights(self) -> bool:
        return len(self.insights) > 0

    @property
    def alert_count(self) -> int:
        return sum(1 for i in self.insights if i.severity in (InsightSeverity.WARNING, InsightSeverity.ALERT))


class BatchScanResult(BaseModel):
    """Result from scanning multiple patients."""

    total_patients: int = 0
    scanned: int = 0
    with_insights: int = 0
    total_insights: int = 0
    total_alerts: int = 0
    errors: int = 0
    duration_ms: int = 0
    results: list[ScanResult] = Field(default_factory=list)
