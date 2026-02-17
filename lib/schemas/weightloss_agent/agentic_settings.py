"""Schemas for weightloss agent settings and GLP-1 injection logging."""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class GlpInjectionSettingsUpsert(BaseModel):
    user_id: UUID
    injection_date: date = Field(
        ..., description="Most recent injection date (local date)."
    )
    injection_frequency_days: Optional[int] = Field(
        7, ge=1, le=30, description="Injection cadence in days."
    )
    timezone: Optional[str] = Field(
        None, description="IANA timezone name, e.g., Asia/Kolkata."
    )
    daily_checkin_time: Optional[str] = Field(
        None, description="Daily check-in time in HH:MM (24h)."
    )


class GlpInjectionSettingsRecord(GlpInjectionSettingsUpsert):
    created_at: datetime
    updated_at: datetime

