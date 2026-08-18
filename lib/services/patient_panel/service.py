"""Assembly + read service for the patient panel signal."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from lib.schemas.patient_panel_signal import (
    GlucoseSource,
    Modality,
    PanelInputs,
    PatientPanelSignal,
)
from lib.services.patient_panel.compute import build_signal
from lib.services.patient_panel.extract import (
    aggregate_daily_cgm,
    smbg_inputs,
    vitals_inputs,
)
from lib.services.patient_panel.store import PatientPanelStore

logger = logging.getLogger(__name__)

ContextProvider = Callable[[str], Awaitable[dict[str, Any]]]

_CGM_WINDOW_DAYS = 14


class PatientPanelService:
    def __init__(
        self,
        *,
        store: PatientPanelStore,
        context_provider: ContextProvider,
        cgm_report_service: Any,
        vital_service: Any,
        smbg_service: Any,
    ):
        self._store = store
        self._context = context_provider
        self._cgm = cgm_report_service
        self._vitals = vital_service
        self._smbg = smbg_service

    async def recompute(self, patient_id: str) -> PatientPanelSignal | None:
        ctx = await self._safe(self._context(patient_id), {})
        if not ctx:
            return None

        merged: dict[str, Any] = {}
        cgm, cgm_reading_count = await self._cgm_window(patient_id)
        merged.update(cgm)
        merged.update(vitals_inputs(await self._safe(self._vitals.get_latest_vitals(patient_id), [])))
        if merged.get("tir_pct") is None:
            merged.update(smbg_inputs(await self._safe(self._smbg.get_patient_smbgs(patient_id), [])))

        inputs = PanelInputs(
            has_any_data=bool(ctx.get("has_any_data", bool(merged))),
            is_pregnant=ctx.get("is_pregnant", False),
            glucose_expected=ctx.get("glucose_expected", True),
            enrolled_days=ctx.get("enrolled_days"),
            last_glucose_days_ago=ctx.get("last_glucose_days_ago"),
            glucose_reading_count_14d=cgm_reading_count,
            glucose_sync_stale=ctx.get("glucose_sync_stale", False),
            glucose_sync_stale_days=ctx.get("glucose_sync_stale_days"),
            weight_delta_kg=ctx.get("weight_delta_kg"),
            adherence_pct=ctx.get("adherence_pct"),
            activity_dropping=ctx.get("activity_dropping", False),
            activity_note=ctx.get("activity_note"),
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
            sources_fresh_as_of=ctx.get("sources_fresh_as_of") or {},
        )
        await self._store.upsert(signal)
        return signal

    async def list_panel(self, **kwargs) -> tuple[list[dict[str, Any]], int]:
        return await self._store.list(**kwargs)

    async def ensure_indexes(self) -> None:
        await self._store.ensure_indexes()

    async def _cgm_window(self, patient_id: str) -> tuple[dict[str, Any], int]:
        end = datetime.now(timezone.utc).replace(tzinfo=None)
        start = end - timedelta(days=_CGM_WINDOW_DAYS)
        reports = await self._safe(self._cgm.fetch_daily_reports(patient_id, start, end), [])
        agg = aggregate_daily_cgm(reports)
        return agg, int(agg.pop("reading_count", 0))

    async def _safe(self, coro: Awaitable[Any], default: Any) -> Any:
        try:
            return await coro
        except Exception:
            logger.exception("panel recompute: a source read failed")
            return default
