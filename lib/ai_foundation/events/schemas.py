"""
Health Event Schemas — typed events for agent-to-agent communication.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class HealthEventType(str, Enum):
    """Standard event types published by agents."""

    # Data events
    MEAL_LOGGED = "meal_logged"
    GLUCOSE_READING = "glucose_reading"
    GLUCOSE_SPIKE = "glucose_spike"
    HYPO_EVENT = "hypo_event"
    FITNESS_LOGGED = "fitness_logged"
    SLEEP_LOGGED = "sleep_logged"
    VITAL_RECORDED = "vital_recorded"

    # Agent events
    PROACTIVE_INSIGHT = "proactive_insight"
    RESPONSE_FLAGGED = "response_flagged"
    GOAL_UPDATED = "goal_updated"
    PATIENT_DISENGAGED = "patient_disengaged"

    # System events
    HOURLY_SCAN = "hourly_scan"
    DAILY_SUMMARY_READY = "daily_summary_ready"
    MODEL_QUALITY_ALERT = "model_quality_alert"


class HealthEvent(BaseModel):
    """A typed event published by an agent or system process."""

    event_id: str = Field(default_factory=lambda: f"evt_{uuid4().hex[:12]}")
    event_type: str = Field(description="Event type from HealthEventType or custom string.")
    patient_id: str = Field(description="The patient this event relates to.")
    data: dict[str, Any] = Field(
        default_factory=dict,
        description="Event-specific payload data.",
    )
    source_agent: str = Field(
        default="system",
        description="Agent or system that published this event.",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional metadata (trace_id, etc.).",
    )
