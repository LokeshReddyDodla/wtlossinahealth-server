"""Assembly orchestration test — fake sources through recompute → store."""

import pytest

from lib.schemas.patient_panel_signal import (
    GlucoseSource,
    Modality,
    PanelAssessment,
)
from lib.services.patient_panel.service import PatientPanelService
from lib.services.patient_panel.store import PatientPanelStore
from tests.services.test_patient_panel_store import FakeCollection


class _CGM:
    def __init__(self, reports):
        self._r = reports

    async def fetch_reports(self, patient_id):
        return self._r


class _Vitals:
    def __init__(self, rows):
        self._rows = rows

    async def get_latest_vitals(self, patient_id):
        return self._rows


class _SMBG:
    def __init__(self, readings):
        self._readings = readings

    async def get_patient_smbgs(self, patient_id):
        return self._readings


def _service(*, ctx, reports=None, vitals=None, smbgs=None):
    store = PatientPanelStore(FakeCollection())
    svc = PatientPanelService(
        store=store,
        context_provider=lambda pid: _async(ctx),
        cgm_report_service=_CGM(reports or []),
        vital_service=_Vitals(vitals or []),
        smbg_service=_SMBG(smbgs or []),
    )
    return svc, store


async def _async(v):
    return v


@pytest.mark.asyncio
async def test_recompute_cgm_patient_builds_at_risk_row():
    ctx = {
        "name": "Sunita Menon", "age": 52, "sex": "F", "conditions": ["T2D 8y"],
        "modality": Modality.CGM, "facility_id": "f1", "care_provider_ids": ["cp1"],
        "has_any_data": True, "last_glucose_source": GlucoseSource.CGM,
    }
    report = {
        "cgm_summary_stats": {"average_glucose_mgdl": 158, "gmi": 7.0,
                              "coefficient_of_variation_percent": 34,
                              "nocturnal_time_below_70_percent": 41},
        "cgm_range_stats": {"in_target_70_180_percent": 78},
        "trend": {"delta_time_in_range_percent": -6},
    }
    svc, store = _service(ctx=ctx, reports=[report])

    sig = await svc.recompute("p1")
    assert sig.assessment is PanelAssessment.AT_RISK
    assert "Nocturnal hypo 41%" in sig.reason
    assert sig.tir_pct == 78 and sig.gmi == 7.0

    rows, total = await store.list(facility_id="f1")
    assert total == 1 and rows[0]["assessment"] == "at_risk"


@pytest.mark.asyncio
async def test_recompute_labs_only_patient_uses_a1c():
    ctx = {"name": "Ramesh", "modality": Modality.LABS, "has_any_data": True,
           "facility_id": "f1"}
    vitals = [{"type": "a1c", "value": 10.5, "time": 0, "source_name": "lab"}]
    svc, _ = _service(ctx=ctx, reports=[], vitals=vitals)
    sig = await svc.recompute("p2")
    assert sig.assessment is PanelAssessment.AT_RISK
    assert "A1c 10.5%" in sig.reason


@pytest.mark.asyncio
async def test_recompute_smbg_fills_when_no_cgm():
    ctx = {"name": "Chinnaiah", "modality": Modality.SMBG, "has_any_data": True,
           "facility_id": "f1"}
    svc, _ = _service(ctx=ctx, reports=[], smbgs=[{"value": 150}, {"value": 154}])
    sig = await svc.recompute("p3")
    assert sig.smbg_avg == 152
    assert sig.assessment is PanelAssessment.WATCH  # > 140 goal


@pytest.mark.asyncio
async def test_recompute_source_failure_degrades_gracefully():
    class _Boom:
        async def fetch_reports(self, pid):
            raise RuntimeError("clickhouse down")

    store = PatientPanelStore(FakeCollection())
    svc = PatientPanelService(
        store=store, context_provider=lambda pid: _async({"name": "X", "has_any_data": True, "facility_id": "f1"}),
        cgm_report_service=_Boom(), vital_service=_Vitals([]), smbg_service=_SMBG([]),
    )
    sig = await svc.recompute("p4")  # must not raise
    assert sig is not None
    rows, total = await store.list(facility_id="f1")
    assert total == 1


@pytest.mark.asyncio
async def test_recompute_uses_newest_cgm_report():
    # fetch_reports is ascending; the newest (last) report must win.
    old = {"cgm_summary_stats": {}, "cgm_range_stats": {"in_target_70_180_percent": 45}, "trend": {}}
    new = {"cgm_summary_stats": {}, "cgm_range_stats": {"in_target_70_180_percent": 96}, "trend": {}}
    ctx = {"name": "Raj", "modality": Modality.CGM, "has_any_data": True, "facility_id": "f1"}
    svc, _ = _service(ctx=ctx, reports=[old, new])
    sig = await svc.recompute("p5")
    assert sig.tir_pct == 96
    assert sig.assessment is PanelAssessment.RESPONDING


@pytest.mark.asyncio
async def test_recompute_no_context_skips():
    svc, store = _service(ctx={})
    assert await svc.recompute("pX") is None
