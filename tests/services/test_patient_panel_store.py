"""Store and pure-extractor tests for the patient panel signal."""

import pytest

from lib.schemas.patient_panel_signal import (
    Modality,
    PanelInputs,
)
from lib.services.patient_panel.compute import build_signal
from lib.services.patient_panel.extract import (
    aggregate_daily_cgm,
    cgm_inputs,
    fitness_inputs,
    smbg_inputs,
    vitals_inputs,
)
from lib.services.patient_panel.store import PatientPanelStore


class _Cursor:
    def __init__(self, rows):
        self._rows = rows

    def sort(self, spec):
        for key, direction in reversed(spec):
            self._rows = sorted(
                self._rows,
                key=lambda d, k=key: (d.get(k) is None, d.get(k)),
                reverse=direction < 0,
            )
        return self

    def skip(self, n):
        self._rows = self._rows[n:]
        return self

    def limit(self, n):
        self._rows = self._rows[:n]
        return self

    async def to_list(self, length=None):
        return self._rows


class FakeCollection:
    def __init__(self):
        self.docs: dict[str, dict] = {}

    async def create_index(self, *a, **k):
        return "idx"

    async def replace_one(self, flt, doc, upsert=False):
        self.docs[flt["patient_id"]] = doc

    async def find_one(self, flt, projection=None):
        for d in self.docs.values():
            if self._match(d, flt):
                r = dict(d)
                r.pop("_id", None)
                return r
        return None

    async def update_one(self, flt, update):
        for d in self.docs.values():
            if self._match(d, flt):
                d.update(update.get("$set", {}))
                return type("R", (), {"matched_count": 1})()
        return type("R", (), {"matched_count": 0})()

    def _match(self, d, q):
        for k, v in q.items():
            if isinstance(v, dict) and "$regex" in v:
                import re
                if not re.search(v["$regex"], str(d.get(k, "")), re.I):
                    return False
            elif k == "care_provider_ids":
                if v not in (d.get(k) or []):
                    return False
            elif d.get(k) != v:
                return False
        return True

    async def count_documents(self, q):
        return sum(1 for d in self.docs.values() if self._match(d, q))

    def find(self, q, projection=None):
        rows = [dict(d) for d in self.docs.values() if self._match(d, q)]
        for r in rows:
            r.pop("_id", None)
        return _Cursor(rows)


def _sig(pid, name, assessment_inputs, **row):
    return build_signal(
        patient_id=pid, name=name, modality=row.pop("modality", Modality.CGM),
        inputs=assessment_inputs, **row,
    )


@pytest.mark.asyncio
async def test_upsert_is_one_row_per_patient():
    store = PatientPanelStore(FakeCollection())
    s = _sig("p1", "A", PanelInputs(has_any_data=True, tir_pct=96))
    await store.upsert(s)
    await store.upsert(s)  # again
    rows, total = await store.list(facility_id=None)
    assert total == 1


@pytest.mark.asyncio
async def test_list_filters_by_status_and_scope():
    store = PatientPanelStore(FakeCollection())
    await store.upsert(_sig("p1", "Sunita", PanelInputs(has_any_data=True, nocturnal_below_70_pct=41),
                            facility_id="f1", care_provider_ids=["cpA"]))
    await store.upsert(_sig("p2", "Raj", PanelInputs(has_any_data=True, tir_pct=96),
                            facility_id="f1", care_provider_ids=["cpB"]))
    rows, total = await store.list(facility_id="f1", status="at_risk")
    assert total == 1 and rows[0]["name"] == "Sunita"
    rows, total = await store.list(facility_id="f1", care_provider_id="cpB", is_facility_admin=False)
    assert total == 1 and rows[0]["name"] == "Raj"


@pytest.mark.asyncio
async def test_list_sorts_and_paginates():
    store = PatientPanelStore(FakeCollection())
    for i, tir in enumerate([96, 55, 72, 40, 88]):
        await store.upsert(_sig(f"p{i}", f"P{i}", PanelInputs(has_any_data=True, tir_pct=tir),
                                facility_id="f1"))
    rows, total = await store.list(facility_id="f1", sort="priority", order=1, limit=2)
    assert total == 5 and len(rows) == 2
    assert rows[0]["assessment"] == "at_risk"


@pytest.mark.asyncio
async def test_list_search_by_name():
    store = PatientPanelStore(FakeCollection())
    await store.upsert(_sig("p1", "Sunita Menon", PanelInputs(has_any_data=True, tir_pct=96), facility_id="f1"))
    await store.upsert(_sig("p2", "Raj Ramanand", PanelInputs(has_any_data=True, tir_pct=96), facility_id="f1"))
    rows, total = await store.list(facility_id="f1", search="raj")
    assert total == 1 and rows[0]["name"] == "Raj Ramanand"


def test_cgm_inputs_from_report():
    report = {
        "cgm_summary_stats": {
            "average_glucose_mgdl": 158, "coefficient_of_variation_percent": 34,
            "gmi": 7.0, "nocturnal_time_below_70_percent": 41,
        },
        "cgm_range_stats": {
            "in_target_70_180_percent": 78, "below_54_percent": 2,
            "below_70_above_54_percent": 6, "above_180_below_250_percent": 12,
            "above_250_percent": 2,
        },
        "trend": {"delta_time_in_range_percent": -6},
        "hypo_events": [{"x": 1}, {"x": 2}],
    }
    out = cgm_inputs(report)
    assert out["tir_pct"] == 78 and out["avg_glucose"] == 158 and out["gmi"] == 7.0
    assert out["below_54_pct"] == 2 and out["below_70_pct"] == 8      # 6 + 2
    assert out["above_180_pct"] == 14                                 # 12 + 2
    assert out["nocturnal_below_70_pct"] == 41 and out["tir_delta"] == -6
    assert out["hypo_events"] == 2


def test_cgm_inputs_pregnancy_range_fallback():
    report = {"cgm_range_stats": {"in_target_63_140_percent": 88}, "cgm_summary_stats": {}, "trend": {}}
    assert cgm_inputs(report)["tir_pct"] == 88


def test_cgm_inputs_empty():
    assert cgm_inputs(None) == {}


def test_vitals_inputs_picks_a1c():
    rows = [
        {"type": "a1c", "value": 10.5, "time": 0, "source_name": "lab"},
        {"type": "weight", "value": 85.6, "time": 0, "source_name": "app"},
        {"type": "fbs", "value": 221, "time": 0, "source_name": "lab"},
    ]
    out = vitals_inputs(rows)
    assert out["a1c"] == 10.5 and out["fasting_glucose"] == 221


def test_smbg_inputs_averages():
    assert smbg_inputs([{"value": 110}, {"value": 130}, {"value": 120}])["smbg_avg"] == 120
    assert smbg_inputs([]) == {}


def test_fitness_inputs_avg_and_activity_drop():
    def day(steps, d):
        return {"steps": steps, "metadata": {"date_range": {"start": d}}}
    reports = [day(3000, "2026-08-01"), day(2500, "2026-08-02"),
               day(300, "2026-08-10"), day(150, "2026-08-11")]
    out = fitness_inputs(reports)
    assert out["avg_steps"] == round((3000 + 2500 + 300 + 150) / 4)
    assert out["activity_dropping"] is True
    assert "steps 2,750→225" in out["activity_note"]

    steady = [day(4000, "2026-08-01"), day(4200, "2026-08-02"),
              day(3900, "2026-08-10"), day(4100, "2026-08-11")]
    assert "activity_dropping" not in fitness_inputs(steady)
    assert fitness_inputs([]) == {}


def test_aggregate_daily_cgm_reading_weighted():
    reports = [
        {"metadata": {"total_readings": 100}, "cgm_summary_stats": {"average_glucose_mgdl": 100},
         "cgm_range_stats": {"in_target_70_180_percent": 50}},
        {"metadata": {"total_readings": 300}, "cgm_summary_stats": {"average_glucose_mgdl": 140},
         "cgm_range_stats": {"in_target_70_180_percent": 90}},
    ]
    out = aggregate_daily_cgm(reports)
    assert out["tir_pct"] == 80.0
    assert out["avg_glucose"] == 130.0
    assert out["gmi"] == round(3.31 + 0.02392 * 130.0, 1)
    assert out["reading_count"] == 400


def test_aggregate_daily_cgm_computes_tir_direction():
    older = {"metadata": {"total_readings": 200, "date_range": {"start": "2026-08-01"}},
             "cgm_range_stats": {"in_target_70_180_percent": 60}}
    newer = {"metadata": {"total_readings": 200, "date_range": {"start": "2026-08-10"}},
             "cgm_range_stats": {"in_target_70_180_percent": 90}}
    out = aggregate_daily_cgm([newer, older])
    assert out["tir_delta"] == 30.0
    assert aggregate_daily_cgm([older])["tir_delta"] is None


def test_aggregate_daily_cgm_skips_zero_reading_days():
    reports = [
        {"metadata": {"total_readings": 0}, "cgm_range_stats": {"in_target_70_180_percent": 10}},
        {"metadata": {"total_readings": 200}, "cgm_range_stats": {"in_target_70_180_percent": 88}},
    ]
    out = aggregate_daily_cgm(reports)
    assert out["tir_pct"] == 88.0 and out["reading_count"] == 200
    assert aggregate_daily_cgm([]) == {}
