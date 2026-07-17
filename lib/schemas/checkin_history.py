"""Schemas for the unified check-in history API."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field


class SleepSnapshot(BaseModel):
    id: str
    quality: int
    hours_slept: float | None = None
    bed_time: str | None = None
    wake_time: str | None = None
    notes: str | None = None


class MoodSnapshot(BaseModel):
    id: str
    level: int
    emoji: str
    tags: list[str] = Field(default_factory=list)
    notes: str | None = None
    recorded_at: datetime


class SymptomItem(BaseModel):
    symptom_name: str
    severity: int
    custom_label: str | None = None


class SymptomSnapshot(BaseModel):
    id: str
    symptoms: list[SymptomItem] = Field(default_factory=list)
    notes: str | None = None
    recorded_at: datetime


class WeightSnapshot(BaseModel):
    value: float
    time: datetime


class CheckinDay(BaseModel):
    date: date
    sleep: SleepSnapshot | None = None
    mood: MoodSnapshot | None = None
    weight: WeightSnapshot | None = None
    symptoms: list[SymptomSnapshot] = Field(default_factory=list)
    xp_earned: int = 0
    tasks_completed: list[str] = Field(default_factory=list)


class WeeklyRecap(BaseModel):
    week_label: str
    dominant_mood_level: int | None = None
    avg_sleep_hours: float | None = None
    symptom_count: int = 0
    completion_rate: float = 0.0
    xp_earned: int = 0
    days_logged: int = 0
    total_days: int = 7


class CheckinSummary(BaseModel):
    total_days_logged: int = 0
    fully_complete_days: int = 0
    completion_rate: float = 0.0
    avg_sleep_hours: float | None = None
    avg_sleep_quality: float | None = None
    dominant_mood: str | None = None
    dominant_mood_level: int | None = None
    total_symptoms_logged: int = 0
    most_common_symptom: str | None = None
    total_xp_earned: int = 0
    current_streak: int = 0
    longest_streak: int = 0
    level: int = 1


class CheckinHistoryResponse(BaseModel):
    days: list[CheckinDay] = Field(default_factory=list)
    summary: CheckinSummary = Field(default_factory=CheckinSummary)
    weekly_recaps: list[WeeklyRecap] = Field(default_factory=list)
    total: int = 0
