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


class InsightCategory(str, Enum):
    """What kind of insight this is."""

    GLUCOSE_SPIKE = "glucose_spike"
    GLUCOSE_HYPO = "glucose_hypo"
    GLUCOSE_IMPROVING = "glucose_improving"
    GLUCOSE_WORSENING = "glucose_worsening"
    MEAL_MISSED = "meal_missed"
    MEAL_HIGH_CARB = "meal_high_carb"
    MEAL_LOW_PROTEIN = "meal_low_protein"
    FITNESS_INACTIVE = "fitness_inactive"
    FITNESS_STREAK = "fitness_streak"
    SLEEP_POOR = "sleep_poor"
    SLEEP_IMPROVING = "sleep_improving"
    ENGAGEMENT_DROP = "engagement_drop"
    GOAL_PROGRESS = "goal_progress"
    GENERAL = "general"


class HealthInsight(BaseModel):
    """A single insight detected by the proactive monitor."""

    insight_id: str = Field(default_factory=lambda: f"ins_{uuid4().hex[:12]}")
    category: InsightCategory
    severity: InsightSeverity
    title: str = Field(description="Short title for push notification (< 60 chars).")
    body: str = Field(description="Insight message (< 200 chars for push, longer for in-app).")
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
