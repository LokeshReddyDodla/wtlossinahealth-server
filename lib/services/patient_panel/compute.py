"""Assemble a PatientPanelSignal from identity + already-gathered PanelInputs."""

from __future__ import annotations

from datetime import datetime, timezone

from lib.schemas.patient_panel_signal import (
    DataConfidence,
    GlucoseSource,
    Modality,
    PanelInputs,
    PatientPanelSignal,
)
from lib.services.patient_panel.rules import classify


def build_signal(
    *,
    patient_id: str,
    name: str,
    modality: Modality,
    inputs: PanelInputs,
    age: int | None = None,
    sex: str | None = None,
    conditions: list[str] | None = None,
    facility_id: str | None = None,
    care_provider_ids: list[str] | None = None,
    last_glucose_at: datetime | None = None,
    last_glucose_source: GlucoseSource = GlucoseSource.NONE,
    last_active_at: datetime | None = None,
    days_of_data: int | None = None,
    sensor_active_pct: float | None = None,
    data_confidence: DataConfidence | None = None,
    sources_fresh_as_of: dict[str, datetime] | None = None,
    now: datetime | None = None,
) -> PatientPanelSignal:
    tri = classify(inputs)
    return PatientPanelSignal(
        patient_id=patient_id,
        facility_id=facility_id,
        care_provider_ids=care_provider_ids or [],
        name=name,
        age=age,
        sex=sex,
        conditions=conditions or [],
        modality=modality,
        assessment=tri.assessment,
        reason=tri.reason,
        reason_severity=tri.severity,
        priority=tri.priority,
        tir_pct=inputs.tir_pct,
        tir_delta=inputs.tir_delta,
        avg_glucose=inputs.avg_glucose,
        cv_pct=inputs.cv_pct,
        gmi=inputs.gmi,
        below_70_pct=inputs.below_70_pct,
        below_54_pct=inputs.below_54_pct,
        above_180_pct=inputs.above_180_pct,
        nocturnal_below_70_pct=inputs.nocturnal_below_70_pct,
        hypo_events=inputs.hypo_events,
        a1c=inputs.a1c,
        fasting_glucose=inputs.fasting_glucose,
        smbg_avg=inputs.smbg_avg,
        weight_delta_kg=inputs.weight_delta_kg,
        last_glucose_at=last_glucose_at,
        last_glucose_source=last_glucose_source,
        glucose_sync_stale=inputs.glucose_sync_stale,
        last_active_at=last_active_at,
        adherence_pct=inputs.adherence_pct,
        days_of_data=days_of_data,
        sensor_active_pct=sensor_active_pct,
        data_confidence=data_confidence,
        computed_at=now or datetime.now(timezone.utc),
        sources_fresh_as_of=sources_fresh_as_of or {},
    )
