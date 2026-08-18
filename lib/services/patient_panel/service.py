"""Assembly + read service for the patient panel signal."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta, timezone
from typing import Any

from lib.schemas.patient_panel_signal import (
    DataConfidence,
    GlucoseSource,
    Modality,
    PanelAssessment,
    PanelInputs,
    PatientPanelSignal,
)
from lib.services.patient_panel.compute import build_signal
from lib.services.patient_panel.extract import (
    aggregate_daily_cgm,
    fitness_inputs,
    sleep_inputs,
    smbg_inputs,
    vitals_inputs,
)
from lib.services.patient_panel.store import PatientPanelStore

logger = logging.getLogger(__name__)

ContextProvider = Callable[[str], Awaitable[dict[str, Any]]]

_WINDOW_DAYS = 14
_CGM_LAPSED_LOOKBACK_DAYS = 60


def _confidence(days: int, sensor_active: float | None) -> DataConfidence | None:
    if not days:
        return None
    if days >= 10 and (sensor_active is None or sensor_active >= 70):
        return DataConfidence.HIGH
    if days >= 4 and (sensor_active is None or sensor_active >= 40):
        return DataConfidence.MEDIUM
    return DataConfidence.LOW


_CONCERNING = {
    PanelAssessment.AT_RISK,
    PanelAssessment.WATCH,
    PanelAssessment.LAPSED,
    PanelAssessment.DATA_GAP,
}


def _parse_dt(v: Any) -> datetime | None:
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(v) if v else None
    except (ValueError, TypeError):
        return None


def _apply_worklist(signal: PatientPanelSignal, prior: dict[str, Any] | None) -> None:
    now = signal.computed_at
    same = bool(prior) and prior.get("assessment") == signal.assessment.value
    signal.reviewed_at = _parse_dt(prior.get("reviewed_at")) if prior else None
    if same:
        signal.state_since = _parse_dt(prior.get("state_since")) or now
        signal.changed_at = _parse_dt(prior.get("changed_at"))
    else:
        signal.state_since = now
        signal.changed_at = now
    concerning = signal.assessment in _CONCERNING
    signal.needs_review = concerning and (
        signal.reviewed_at is None or signal.reviewed_at < signal.state_since
    )


class PatientPanelService:
    def __init__(
        self,
        *,
        store: PatientPanelStore,
        context_provider: ContextProvider,
        cgm_report_service: Any,
        vital_service: Any,
        smbg_service: Any,
        fitness_report_service: Any,
        sleep_report_service: Any,
    ):
        self._store = store
        self._context = context_provider
        self._cgm = cgm_report_service
        self._vitals = vital_service
        self._smbg = smbg_service
        self._fitness = fitness_report_service
        self._sleep = sleep_report_service

    async def recompute(self, patient_id: str) -> PatientPanelSignal | None:
        ctx = await self._safe(self._context(patient_id), {})
        if not ctx:
            return None

        merged: dict[str, Any] = {}
        cgm, cgm_meta = await self._cgm_window(patient_id, _WINDOW_DAYS)
        if not cgm and ctx.get("glucose_sync_stale"):
            cgm, cgm_meta = await self._cgm_window(patient_id, _CGM_LAPSED_LOOKBACK_DAYS)
        merged.update(cgm)
        merged.update(vitals_inputs(await self._safe(self._vitals.get_latest_vitals(patient_id), [])))
        if merged.get("tir_pct") is None:
            merged.update(smbg_inputs(await self._safe(self._smbg.get_patient_smbgs(patient_id), [])))
        fitness = await self._fitness_window(patient_id)
        sleep = await self._sleep_window(patient_id)

        inputs = PanelInputs(
            has_any_data=bool(ctx.get("has_any_data", bool(merged) or bool(fitness))),
            is_pregnant=ctx.get("is_pregnant", False),
            glucose_expected=ctx.get("glucose_expected", True),
            enrolled_days=ctx.get("enrolled_days"),
            last_glucose_days_ago=ctx.get("last_glucose_days_ago"),
            glucose_reading_count_14d=cgm_meta["reading_count"],
            glucose_sync_stale=ctx.get("glucose_sync_stale", False),
            glucose_sync_stale_days=ctx.get("glucose_sync_stale_days"),
            weight_delta_kg=ctx.get("weight_delta_kg"),
            adherence_pct=ctx.get("adherence_pct"),
            activity_dropping=fitness.get("activity_dropping", False),
            activity_note=fitness.get("activity_note"),
            **merged,
        )

        signal = build_signal(
            patient_id=patient_id,
            name=ctx.get("name", ""),
            age=ctx.get("age"),
            sex=ctx.get("sex"),
            conditions=ctx.get("conditions") or [],
            modality=ctx.get("modality") or Modality.NONE,
            facility_id=ctx.get("facility_id"),
            care_provider_ids=ctx.get("care_provider_ids") or [],
            inputs=inputs,
            last_glucose_at=ctx.get("last_glucose_at"),
            last_glucose_source=ctx.get("last_glucose_source") or GlucoseSource.NONE,
            last_active_at=ctx.get("last_active_at"),
            avg_steps=fitness.get("avg_steps"),
            avg_sleep_hours=sleep.get("avg_sleep_hours"),
            days_of_data=cgm_meta["days_of_data"],
            sensor_active_pct=cgm_meta["sensor_active_pct"],
            data_confidence=cgm_meta["data_confidence"],
            sources_fresh_as_of=ctx.get("sources_fresh_as_of") or {},
        )
        _apply_worklist(signal, await self._store.get(patient_id))
        await self._store.upsert(signal)
        return signal

    async def list_panel(self, **kwargs) -> tuple[list[dict[str, Any]], int]:
        return await self._store.list(**kwargs)

    async def mark_reviewed(self, patient_id: str) -> bool:
        return await self._store.mark_reviewed(
            patient_id, datetime.now(timezone.utc).isoformat()
        )

    async def ensure_indexes(self) -> None:
        await self._store.ensure_indexes()

    async def _fitness_window(self, patient_id: str) -> dict[str, Any]:
        end = date.today()
        start = end - timedelta(days=_WINDOW_DAYS)
        reports = await self._safe(
            self._fitness.fetch_daily_reports_in_range(patient_id, start, end), []
        )
        return fitness_inputs(reports)

    async def _sleep_window(self, patient_id: str) -> dict[str, Any]:
        end = date.today()
        start = end - timedelta(days=_WINDOW_DAYS)
        reports = await self._safe(
            self._sleep.fetch_daily_reports_in_range(patient_id, start, end), []
        )
        return sleep_inputs(reports)

    async def _cgm_window(self, patient_id: str, days: int) -> tuple[dict[str, Any], dict[str, Any]]:
        end = datetime.now(timezone.utc).replace(tzinfo=None)
        start = end - timedelta(days=days)
        reports = await self._safe(self._cgm.fetch_daily_reports(patient_id, start, end), [])
        agg = aggregate_daily_cgm(reports)
        days = int(agg.pop("days_of_data", 0) or 0)
        sensor_active = agg.pop("sensor_active_pct", None)
        meta = {
            "reading_count": int(agg.pop("reading_count", 0) or 0),
            "days_of_data": days,
            "sensor_active_pct": sensor_active,
            "data_confidence": _confidence(days, sensor_active),
        }
        return agg, meta

    async def _safe(self, coro: Awaitable[Any], default: Any) -> Any:
        try:
            return await coro
        except Exception:
            logger.exception("panel recompute: a source read failed")
            return default
