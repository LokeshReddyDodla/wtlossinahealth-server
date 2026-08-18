"""Assembly orchestration test — fake sources through recompute → store."""

import pytest

from lib.schemas.patient_panel_signal import (
    DataConfidence,
    GlucoseSource,
    Modality,
    PanelAssessment,
)
from lib.services.patient_panel.service import PatientPanelService, _confidence
from lib.services.patient_panel.store import PatientPanelStore
from tests.services.test_patient_panel_store import FakeCollection


class _CGM:
    def __init__(self, reports):
        self._r = reports

    async def fetch_daily_reports(self, patient_id, start, end):
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


class _Fitness:
    def __init__(self, reports):
        self._r = reports

    async def fetch_daily_reports_in_range(self, patient_id, start, end):
        return self._r


class _Sleep:
    def __init__(self, reports):
        self._r = reports

    async def fetch_daily_reports_in_range(self, patient_id, start, end):
        return self._r


def _service(*, ctx, reports=None, vitals=None, smbgs=None, fitness=None, sleep=None):
    store = PatientPanelStore(FakeCollection())
    svc = PatientPanelService(
        store=store,
        context_provider=lambda pid: _async(ctx),
        cgm_report_service=_CGM(reports or []),
        vital_service=_Vitals(vitals or []),
        smbg_service=_SMBG(smbgs or []),
        fitness_report_service=_Fitness(fitness or []),
        sleep_report_service=_Sleep(sleep or []),
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
        "metadata": {"total_readings": 288},
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
    assert sig.tir_pct == 78 and sig.gmi == 7.1
    assert sig.days_of_data == 1 and sig.data_confidence is DataConfidence.LOW

    rows, total = await store.list(facility_id="f1")
    assert total == 1 and rows[0]["assessment"] == "at_risk"


def test_confidence_tiers():
    assert _confidence(0, None) is None
    assert _confidence(12, 80) is DataConfidence.HIGH
    assert _confidence(12, 30) is DataConfidence.LOW
    assert _confidence(5, 60) is DataConfidence.MEDIUM
    assert _confidence(2, 90) is DataConfidence.LOW
    assert _confidence(12, None) is DataConfidence.HIGH


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
    from types import SimpleNamespace
    smbgs = [SimpleNamespace(glucose_level=150), SimpleNamespace(glucose_level=154)]
    svc, _ = _service(ctx=ctx, reports=[], smbgs=smbgs)
    sig = await svc.recompute("p3")
    assert sig.smbg_avg == 152
    assert sig.assessment is PanelAssessment.WATCH  # > 140 goal


@pytest.mark.asyncio
async def test_recompute_source_failure_degrades_gracefully():
    class _Boom:
        async def fetch_daily_reports(self, pid, start, end):
            raise RuntimeError("clickhouse down")

    store = PatientPanelStore(FakeCollection())
    svc = PatientPanelService(
        store=store, context_provider=lambda pid: _async({"name": "X", "has_any_data": True, "facility_id": "f1"}),
        cgm_report_service=_Boom(), vital_service=_Vitals([]), smbg_service=_SMBG([]),
        fitness_report_service=_Fitness([]), sleep_report_service=_Sleep([]),
    )
    sig = await svc.recompute("p4")  # must not raise
    assert sig is not None
    rows, total = await store.list(facility_id="f1")
    assert total == 1


@pytest.mark.asyncio
async def test_recompute_aggregates_daily_cgm_reading_weighted():
    day_a = {"metadata": {"total_readings": 100},
             "cgm_summary_stats": {"average_glucose_mgdl": 120},
             "cgm_range_stats": {"in_target_70_180_percent": 60}}
    day_b = {"metadata": {"total_readings": 300},
             "cgm_summary_stats": {"average_glucose_mgdl": 120},
             "cgm_range_stats": {"in_target_70_180_percent": 96}}
    ctx = {"name": "Raj", "modality": Modality.CGM, "has_any_data": True, "facility_id": "f1"}
    svc, _ = _service(ctx=ctx, reports=[day_a, day_b])
    sig = await svc.recompute("p5")
    assert sig.tir_pct == 87.0
    assert sig.assessment is PanelAssessment.RESPONDING


@pytest.mark.asyncio
async def test_worklist_needs_review_and_mark_reviewed():
    ctx = {"name": "Sunita", "modality": Modality.CGM, "has_any_data": True,
           "facility_id": "f1", "care_provider_ids": ["cp1"]}
    report = {"metadata": {"total_readings": 288},
              "cgm_summary_stats": {"nocturnal_time_below_70_percent": 41},
              "cgm_range_stats": {"in_target_70_180_percent": 78}}
    svc, store = _service(ctx=ctx, reports=[report])

    first = await svc.recompute("p1")
    assert first.assessment is PanelAssessment.AT_RISK
    assert first.needs_review is True and first.state_since is not None

    again = await svc.recompute("p1")
    assert again.needs_review is True
    assert again.state_since == first.state_since

    assert await svc.mark_reviewed("p1") == "ok"
    reviewed = await svc.recompute("p1")
    assert reviewed.needs_review is False


@pytest.mark.asyncio
async def test_mark_reviewed_rejects_stale_state():
    ctx = {"name": "Sunita", "modality": Modality.CGM, "has_any_data": True, "facility_id": "f1"}
    report = {"metadata": {"total_readings": 288},
              "cgm_range_stats": {"in_target_70_180_percent": 96}}
    svc, store = _service(ctx=ctx, reports=[report])

    await svc.recompute("p1")  # RESPONDING
    stale_state_since = (await store.get("p1"))["state_since"]  # the string the CP's UI holds

    svc._cgm._r = [{"metadata": {"total_readings": 288},
                    "cgm_summary_stats": {"nocturnal_time_below_70_percent": 41},
                    "cgm_range_stats": {"in_target_70_180_percent": 40}}]
    escalated = await svc.recompute("p1")  # AT_RISK, new state_since
    assert escalated.assessment is PanelAssessment.AT_RISK

    # Reviewer acknowledging the state they saw (RESPONDING) must NOT clear the escalation.
    assert await svc.mark_reviewed("p1", stale_state_since) == "stale"
    after = await svc.recompute("p1")
    assert after.needs_review is True

    # Acknowledging the current state succeeds.
    current_state_since = (await store.get("p1"))["state_since"]
    assert await svc.mark_reviewed("p1", current_state_since) == "ok"
    assert (await svc.recompute("p1")).needs_review is False


@pytest.mark.asyncio
async def test_worklist_resurfaces_on_change():
    ctx = {"name": "Raj", "modality": Modality.CGM, "has_any_data": True, "facility_id": "f1"}
    good = {"metadata": {"total_readings": 288}, "cgm_range_stats": {"in_target_70_180_percent": 96}}
    svc, _ = _service(ctx=ctx, reports=[good])
    resp = await svc.recompute("p2")
    assert resp.assessment is PanelAssessment.RESPONDING and resp.needs_review is False

    svc._cgm._r = [{"metadata": {"total_readings": 288}, "cgm_range_stats": {"in_target_70_180_percent": 40}}]
    worse = await svc.recompute("p2")
    assert worse.assessment is PanelAssessment.AT_RISK
    assert worse.needs_review is True and worse.changed_at is not None


@pytest.mark.asyncio
async def test_recompute_activity_drop_from_fitness():
    ctx = {"name": "Nagarjuna", "modality": Modality.CGM, "has_any_data": True, "facility_id": "f1"}
    cgm = [{"metadata": {"total_readings": 288}, "cgm_range_stats": {"in_target_70_180_percent": 96}}]

    def day(steps, d):
        return {"steps": steps, "metadata": {"date_range": {"start": d}}}

    fit = [day(3000, "2026-08-01"), day(2800, "2026-08-02"),
           day(200, "2026-08-10"), day(150, "2026-08-11")]
    svc, _ = _service(ctx=ctx, reports=cgm, fitness=fit)
    sig = await svc.recompute("p9")
    assert sig.assessment is PanelAssessment.WATCH
    assert "steps" in sig.reason
    assert sig.avg_steps is not None


@pytest.mark.asyncio
async def test_recompute_no_context_skips():
    svc, store = _service(ctx={})
    assert await svc.recompute("pX") is None


@pytest.mark.asyncio
async def test_recompute_deletes_orphan_row_when_patient_gone():
    good = {"metadata": {"total_readings": 288}, "cgm_range_stats": {"in_target_70_180_percent": 96}}
    svc, store = _service(ctx={"name": "R", "modality": Modality.CGM, "has_any_data": True,
                               "facility_id": "f1"}, reports=[good])
    await svc.recompute("pZ")
    assert await store.get("pZ") is not None

    svc._context = lambda pid: _async({})  # patient hard-deleted
    assert await svc.recompute("pZ") is None
    assert await store.get("pZ") is None  # orphan row removed
