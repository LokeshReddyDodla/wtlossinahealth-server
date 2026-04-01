"""Pydantic schemas for daily check-in (sleep + mood) endpoints."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class SleepCheckinInput(BaseModel):
    quality: int = Field(..., ge=1, le=5, description="Sleep quality 1-5")
    hours_slept: float = Field(..., ge=0, le=24, description="Hours slept")
    bed_time: str = Field(..., description="Bed time in HH:MM format")
    wake_time: str = Field(..., description="Wake time in HH:MM format")
    checkin_date: date = Field(..., description="Date of check-in (patient's local date)")
    notes: Optional[str] = Field(None, max_length=500)


class MoodEntryInput(BaseModel):
    level: int = Field(..., ge=1, le=5, description="Mood level 1-5")
    emoji: Literal["very_bad", "bad", "neutral", "good", "great"]
    tags: list[str] = Field(default_factory=list, max_length=10)
    recorded_at: datetime = Field(..., description="When the mood was felt (patient's local time)")
    notes: Optional[str] = Field(None, max_length=500)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class SleepCheckinResponse(BaseModel):
    id: str
    patient_id: str
    checkin_date: date
    quality: int
    hours_slept: float
    bed_time: str
    wake_time: str
    notes: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class MoodEntryResponse(BaseModel):
    id: str
    patient_id: str
    level: int
    emoji: str
    tags: list[str] = Field(default_factory=list)
    notes: Optional[str] = None
    recorded_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Trend models
# ---------------------------------------------------------------------------


class SleepPeriod(BaseModel):
    label: str
    avg_quality: float
    avg_hours: float
    count: int


class SleepTrendsResponse(BaseModel):
    periods: list[SleepPeriod]
    current_streak: int
    longest_streak: int


class MoodPeriod(BaseModel):
    label: str
    avg_level: float
    count: int
    top_tags: list[str] = Field(default_factory=list)


class MoodTrendsResponse(BaseModel):
    periods: list[MoodPeriod]
    current_streak: int
    longest_streak: int
