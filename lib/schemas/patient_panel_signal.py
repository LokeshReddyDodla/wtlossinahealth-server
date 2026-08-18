"""Typed contract for the patient panel signal. Design: docs/patient-panel-signal-spec.md."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class PanelAssessment(str, Enum):
    RESPONDING = "responding"
    WATCH = "watch"
    AT_RISK = "at_risk"
    LAPSED = "lapsed"
    DATA_GAP = "data_gap"
    NOT_STARTED = "not_started"


class ReasonSeverity(str, Enum):
    URGENT = "urgent"
    WATCH = "watch"
    INFO = "info"


class DataConfidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class GlucoseSource(str, Enum):
    CGM = "cgm"
    SMBG = "smbg"
    LABS = "labs"
    NONE = "none"


class Modality(str, Enum):
    CGM = "cgm"
    SMBG = "smbg"
    LABS = "labs"
    WEIGHT = "weight"
    NONE = "none"


class PanelInputs(BaseModel):
    is_pregnant: bool = False
    glucose_expected: bool = True
    enrolled_days: int | None = None

    has_any_data: bool = False
    last_glucose_days_ago: float | None = None
    glucose_reading_count_14d: int = 0
    glucose_sync_stale: bool = False
    glucose_sync_stale_days: int | None = None

    tir_pct: float | None = None
    tir_delta: float | None = None
    avg_glucose: float | None = None
    cv_pct: float | None = None
    gmi: float | None = None
    below_70_pct: float | None = None
    below_54_pct: float | None = None
    above_180_pct: float | None = None
    nocturnal_below_70_pct: float | None = None
    hypo_events: int | None = None

    a1c: float | None = None
    fasting_glucose: float | None = None
    smbg_avg: float | None = None

    weight_delta_kg: float | None = None
    adherence_pct: float | None = None
    activity_dropping: bool = False
    activity_note: str | None = None


class Triage(BaseModel):
    assessment: PanelAssessment
    reason: str
    severity: ReasonSeverity
    priority: int


class PatientPanelSignal(BaseModel):
    patient_id: str
    facility_id: str | None = None
    care_provider_ids: list[str] = Field(default_factory=list)

    name: str
    age: int | None = None
    sex: str | None = None
    conditions: list[str] = Field(default_factory=list)
    modality: Modality

    assessment: PanelAssessment
    reason: str
    reason_severity: ReasonSeverity
    priority: int

    tir_pct: float | None = None
    tir_delta: float | None = None
    avg_glucose: float | None = None
    cv_pct: float | None = None
    gmi: float | None = None
    below_70_pct: float | None = None
    below_54_pct: float | None = None
    above_180_pct: float | None = None
    nocturnal_below_70_pct: float | None = None
    hypo_events: int | None = None
    a1c: float | None = None
    fasting_glucose: float | None = None
    smbg_avg: float | None = None
    weight_delta_kg: float | None = None

    last_glucose_at: datetime | None = None
    last_glucose_source: GlucoseSource = GlucoseSource.NONE
    glucose_sync_stale: bool = False
    last_active_at: datetime | None = None
    adherence_pct: float | None = None
    avg_steps: int | None = None
    avg_sleep_hours: float | None = None

    days_of_data: int | None = None
    sensor_active_pct: float | None = None
    data_confidence: DataConfidence | None = None

    state_since: datetime | None = None
    changed_at: datetime | None = None
    reviewed_at: datetime | None = None
    needs_review: bool = False

    computed_at: datetime
    sources_fresh_as_of: dict[str, datetime] = Field(default_factory=dict)
