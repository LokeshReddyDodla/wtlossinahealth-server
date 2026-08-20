"""Pydantic schemas for patient notification inbox endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from lib.core.types import NotificationSeverityLiteral


class NotificationResponse(BaseModel):
    id: str
    patient_id: str
    # Open set: the broker accepts dynamic categories (policy.py owns their
    # semantics and defaults unknowns to the safe tier), so a closed Literal
    # here 500s the list the moment a new category is written.
    category: str
    title: str
    body: str
    severity: Optional[NotificationSeverityLiteral] = None
    deeplink: Optional[str] = None
    data: dict[str, Any] = Field(default_factory=dict)
    dose_status: Optional[str] = Field(
        default=None,
        description="For medication_dose only: 'pending' | 'taken' | 'missed'",
    )
    read_at: Optional[datetime] = None
    dismissed_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class NotificationListResponse(BaseModel):
    notifications: list[NotificationResponse]
    total: int
    unread_count: int
    limit: int
    offset: int


class MarkReadResponse(BaseModel):
    updated: int
