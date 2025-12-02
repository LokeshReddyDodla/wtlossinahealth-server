"""Safety rule evaluation request/response schemas."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class SafetyValidationRequest(BaseModel):
    user_id: UUID
    medications: List[str] = Field(default_factory=list)
    conditions: Dict[str, Any] = Field(default_factory=dict)
    inbody: Dict[str, Any] = Field(default_factory=dict)
    fitness: Dict[str, Any] = Field(default_factory=dict)
    willingness: Dict[str, Any] = Field(default_factory=dict)


class SafetyAction(BaseModel):
    rule_id: str
    type: str
    metric: Optional[str] = None
    value: Optional[float] = None
    units: Optional[str] = None
    severity: str
    rationale_source_id: Optional[str] = None


class SafetyValidationResponse(BaseModel):
    contraindications: List[SafetyAction] = Field(default_factory=list)
    intensity_caps: List[SafetyAction] = Field(default_factory=list)
    rationale_ids: List[str] = Field(default_factory=list)
