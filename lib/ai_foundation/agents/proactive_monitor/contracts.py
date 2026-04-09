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
    MOOD_LOW = "mood_low"

    # Positives (LLM-generated)
    GLUCOSE_IMPROVING = "glucose_improving"
    FITNESS_STREAK = "fitness_streak"
    SLEEP_IMPROVING = "sleep_improving"
    MOOD_IMPROVING = "mood_improving"
    GOAL_PROGRESS = "goal_progress"

    # Cross-domain (LLM-generated)
    SLEEP_GLUCOSE_CORRELATION = "sleep_glucose_correlation"
    SLEEP_MOOD_CORRELATION = "sleep_mood_correlation"
    MEAL_SPIKE_PATTERN = "meal_spike_pattern"
    ACTIVITY_GLUCOSE_BENEFIT = "activity_glucose_benefit"
    LIFESTYLE_PATTERN = "lifestyle_pattern"

    # Goal tracking (LLM-generated)
    STREAK_MAINTAINED = "streak_maintained"
    TARGET_HIT = "target_hit"
    IMPROVEMENT_TREND = "improvement_trend"

    # Coaching nudges (LLM-generated, actionable recommendations)
    COACHING_HABIT = "coaching_habit"
    COACHING_CELEBRATION = "coaching_celebration"
    COACHING_CORRECTION = "coaching_correction"
    COACHING_MEDICATION = "coaching_medication"

    # Static only (generated without LLM, never by LLM)
    MEAL_MISSED = "meal_missed"
    ENGAGEMENT_DROP = "engagement_drop"

    # Daily brief (pipeline-generated, morning scans only)
    DAILY_BRIEF = "daily_brief"

    # Neutral
    GENERAL = "general"


# Categories the LLM can pick from (excludes static-only ones)
_CONCERN_CATEGORIES = [
    InsightCategory.GLUCOSE_SPIKE, InsightCategory.GLUCOSE_HYPO,
    InsightCategory.GLUCOSE_RAPID_SPIKE, InsightCategory.GLUCOSE_RAPID_DROP,
    InsightCategory.GLUCOSE_WORSENING, InsightCategory.MEAL_HIGH_CARB,
    InsightCategory.MEAL_LOW_PROTEIN, InsightCategory.FITNESS_INACTIVE,
    InsightCategory.SLEEP_POOR, InsightCategory.MOOD_LOW,
]
_POSITIVE_CATEGORIES = [
    InsightCategory.GLUCOSE_IMPROVING, InsightCategory.FITNESS_STREAK,
    InsightCategory.SLEEP_IMPROVING, InsightCategory.MOOD_IMPROVING,
    InsightCategory.GOAL_PROGRESS,
    InsightCategory.STREAK_MAINTAINED, InsightCategory.TARGET_HIT,
    InsightCategory.IMPROVEMENT_TREND,
]
_COACHING_CATEGORIES = [
    InsightCategory.COACHING_HABIT,
    InsightCategory.COACHING_CELEBRATION,
    InsightCategory.COACHING_CORRECTION,
    InsightCategory.COACHING_MEDICATION,
]
_CROSS_DOMAIN_CATEGORIES = [
    InsightCategory.SLEEP_GLUCOSE_CORRELATION,
    InsightCategory.SLEEP_MOOD_CORRELATION,
    InsightCategory.MEAL_SPIKE_PATTERN,
    InsightCategory.ACTIVITY_GLUCOSE_BENEFIT,
    InsightCategory.LIFESTYLE_PATTERN,
]

LLM_INSIGHT_CATEGORIES_PROMPT = (
    "CATEGORIES — pick the one that fits best:\n"
    f"Concerns: {', '.join(c.value for c in _CONCERN_CATEGORIES)}\n"
    f"Positives: {', '.join(c.value for c in _POSITIVE_CATEGORIES)}\n"
    f"Cross-domain: {', '.join(c.value for c in _CROSS_DOMAIN_CATEGORIES)}\n"
    f"Coaching nudges: {', '.join(c.value for c in _COACHING_CATEGORIES)}\n"
    "Neutral: general"
)


class HealthInsight(BaseModel):
    """A single insight detected by the proactive monitor."""

    insight_id: str = Field(default_factory=lambda: f"ins_{uuid4().hex[:12]}")
    category: InsightCategory
    severity: InsightSeverity
    title: str = Field(max_length=50, description="Push notification title. Max 50 characters.")
    body: str = Field(max_length=300, description="Push notification body. Max 300 characters for daily briefs, ~180 for individual insights.")
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


class DailyBrief(BaseModel):
    """Single cohesive morning digest combining all health domains."""

    title: str = Field(max_length=50, description="Push notification title. Max 50 chars, start with 📋 emoji.")
    body: str = Field(max_length=300, description="Cohesive daily summary covering all domains. Max 300 chars.")
    categories_covered: list[InsightCategory] = Field(
        default_factory=list,
        description="Which insight categories this brief covers (for dedup tracking).",
    )
    top_severity: InsightSeverity = Field(
        default=InsightSeverity.INFO,
        description="Highest severity among the topics covered.",
    )
    suggested_query: str | None = Field(
        default=None,
        description="Follow-up query the patient could ask.",
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
