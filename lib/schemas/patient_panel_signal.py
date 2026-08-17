"""Typed contract for the patient panel signal — the read model behind the
enriched Patients roster and the Panel triage view.

One row per patient. Every clinical field is optional so a patient on SMBG,
labs, weight-only, or nothing is a first-class row (CGM fields resolve to None).
Full design: docs/patient-panel-signal-spec.md.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class PanelAssessment(str, Enum):
    RESPONDING = "responding"
    WATCH = "watch"
    AT_RISK = "at_risk"
    DATA_GAP = "data_gap"
    NOT_STARTED = "not_started"


class ReasonSeverity(str, Enum):
    URGENT = "urgent"
    WATCH = "watch"
    INFO = "info"


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
    """Per-patient signals assembled from source services, before classification.
    Pure data — the rule engine reads only this, so it stays fully testable."""

    # condition context — drives condition-aware thresholds and whether glucose
    # is even expected (a weight-loss, non-diabetic patient has no glucose gap).
    is_pregnant: bool = False
    glucose_expected: bool = True
    enrolled_days: int | None = None

    # glucose availability
    has_any_data: bool = False
    last_glucose_days_ago: float | None = None
    glucose_reading_count_14d: int = 0
    glucose_sync_stale: bool = False
    glucose_sync_stale_days: int | None = None

    # CGM metrics (nullable)
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

    # labs / SMBG
    a1c: float | None = None
    fasting_glucose: float | None = None
    smbg_avg: float | None = None

    # other modalities / engagement
    weight_delta_kg: float | None = None
    adherence_pct: float | None = None
    activity_dropping: bool = False
    activity_note: str | None = None


class Triage(BaseModel):
    """Deterministic classification output — the heart of the read model."""

    assessment: PanelAssessment
    reason: str
    severity: ReasonSeverity
    priority: int  # ascending sort key; lower = needs attention sooner


class PatientPanelSignal(BaseModel):
    """One materialized row per patient. See docs/patient-panel-signal-spec.md."""

    patient_id: str
    facility_id: str | None = None
    care_provider_ids: list[str] = Field(default_factory=list)

    # identity
    name: str
    age: int | None = None
    sex: str | None = None
    conditions: list[str] = Field(default_factory=list)
    modality: Modality

    # triage (deterministic)
    assessment: PanelAssessment
    reason: str
    reason_severity: ReasonSeverity
    priority: int

    # metrics echoed for grid columns; all nullable
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

    # engagement
    last_glucose_at: datetime | None = None
    last_glucose_source: GlucoseSource = GlucoseSource.NONE
    glucose_sync_stale: bool = False
    last_active_at: datetime | None = None
    adherence_pct: float | None = None

    # provenance — per-source freshness for auditability
    computed_at: datetime
    sources_fresh_as_of: dict[str, datetime] = Field(default_factory=dict)
