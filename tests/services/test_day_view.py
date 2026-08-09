"""Pure-logic checks for the day-view mappers and spine degradation.

No database — every function under test takes plain dicts/lists. The DB paths
(repository) and the gather orchestration (resolver) are exercised separately.
"""

from datetime import datetime

from lib.schemas.day_view import (
    DoseMarker,
    GlucoseRollup,
    Spine,
    SpineEvent,
    SpineSource,
    VitalMarker,
)
from lib.services.day_view import mappers as M

_CGM_REP = {
    "cgm_readings": [
        {"device_timestamp": "2026-08-06T00:00:00", "glucose_mgdl": 86},
        {"device_timestamp": "2026-08-06T03:00:00", "glucose_mgdl": 66},
    ],
    "cgm_range_stats": {"in_target_70_180_percent": 78},
    "cgm_summary_stats": {"average_glucose_mgdl": 132, "gri": 42},
    "hypo_stats": {"hypo_events": [
        {"start_time": "2026-08-06T02:18:00", "end_time": "2026-08-06T03:42:00", "lowest_glucose_mgdl": 66}
    ]},
    "hyper_stats": {"hyper_events": [
        {"start_time": "2026-08-06T20:24:00", "end_time": "2026-08-06T22:18:00", "peak_glucose_mgdl": 205}
    ]},
}
_SMBG = [(6.8, 94.0), (8.2, 148.0)]


# ── spine degradation ────────────────────────────────────────────────────────

def test_spine_prefers_cgm():
    spine = M.select_spine(_CGM_REP, _SMBG)
    assert spine.source is SpineSource.cgm
    assert len(spine.points) == 2
    assert {e.type for e in spine.events} == {"hypo", "hyper"}
    assert spine.band == (70.0, 180.0)


def test_spine_falls_to_smbg_without_cgm():
    spine = M.select_spine(None, _SMBG)
    assert spine.source is SpineSource.smbg
    assert spine.points == _SMBG
    assert not spine.events  # dots carry no excursion spans


def test_hr_is_never_the_spine():
    # HR has its own lane; no glucose means an empty plot, not an HR spine.
    spine = M.select_spine(None, [])
    assert spine.source is SpineSource.none


def test_spine_none_when_nothing():
    spine = M.select_spine(None, [])
    assert spine.source is SpineSource.none
    assert spine.points == []


def test_cgm_with_empty_readings_is_not_a_cgm_spine():
    # A report present but curve-less must not win the spine over SMBG.
    spine = M.select_spine({"cgm_summary_stats": {"average_glucose_mgdl": 130}}, _SMBG)
    assert spine.source is SpineSource.smbg


# ── extraction ───────────────────────────────────────────────────────────────

def test_meal_markers_carry_real_fields():
    rep = {"meal_count": 4, "calories": 1840, "diet_recommendations": {"calories": 2000},
           "meals": [{"time": "20:42:00", "type": "dinner", "name": "Dinner", "score": 0.45,
                      "glucose_response": {"delta_mgdl": 54},
                      "glucose_comparison": {"outcome": "above", "predicted_low": 30, "predicted_high": 48},
                      "total_macro_nutritional_value": {"carbohydrates": 68}}]}
    m = M.meal_markers(rep)[0]
    assert (m.delta_mgdl, m.score, m.comparison, m.predicted, m.carbs_g) == (54, 0.45, "above", (30.0, 48.0), 68)
    n = M.nutrition_rollup(rep)
    assert (n.kcal, n.kcal_target, n.meals) == (1840, 2000, 4)


def test_sleep_hypnogram_from_report_maps_and_clips():
    day_start = datetime(2026, 8, 6, 0, 0)
    rep = {
        "hypnogram": [
            # night crosses midnight → the pre-midnight tail clips to hour 0
            {"start": "2026-08-05T23:48:00", "end": "2026-08-06T00:20:00", "stage": "light"},
            {"start": "2026-08-06T00:20:00", "end": "2026-08-06T01:05:00", "stage": "deep"},
            {"start": "2026-08-06T05:50:00", "end": "2026-08-06T06:12:00", "stage": "rem"},
        ]
    }
    spans = M.sleep_stages_from_report(rep, day_start)
    assert spans[0] == (0.0, round(20 / 60, 3), "light")
    assert spans[1] == (round(20 / 60, 3), round(65 / 60, 3), "deep")
    assert spans[2] == (round(350 / 60, 3), round(372 / 60, 3), "rem")


def test_sleep_hypnogram_absent_is_empty():
    day_start = datetime(2026, 8, 6, 0, 0)
    assert M.sleep_stages_from_report(None, day_start) == []
    assert M.sleep_stages_from_report({}, day_start) == []  # report without the field


def test_hour_of_parses_forms():
    assert abs(M.hour_of("2026-08-06T20:42:00") - 20.7) < 0.01
    assert abs(M.hour_of("12:30:00") - 12.5) < 0.001
    assert M.hour_of(None) is None
    assert M.hour_of("not-a-time") is None


def test_missing_keys_never_crash():
    assert M.cgm_spine({}) is None
    assert M.cgm_spine(None) is None
    assert M.meal_markers(None) == []
    assert M.steps_lane(None).hourly == []
    roll, asleep, eff = M.sleep_rollup(None)
    assert (asleep, eff) == (None, None)


# ── deterministic clinical alerts ────────────────────────────────────────────

_TAKEN = DoseMarker(t=8, slot="morning", label="M", status="taken", taken=True)
_MISSED = DoseMarker(t=20, slot="evening", label="E", status="missed", taken=False)


def _cgm(events: list[SpineEvent] | None = None) -> Spine:
    return Spine(source=SpineSource.cgm, unit="mg/dL", band=(70.0, 180.0), events=events or [])


def test_alerts_flag_a_bad_day():
    g = GlucoseRollup(tir_pct=48)
    spine = _cgm([
        SpineEvent(type="hypo", start=3.2, end=3.7, peak=48),   # peak = nadir for hypo
        SpineEvent(type="hyper", start=20.0, end=22.0, peak=288),
    ])
    bp = [VitalMarker(t=14.0, systolic=148, diastolic=96)]
    alerts = M.day_alerts(g, spine, bp, [_MISSED, _TAKEN])
    cats = {a.category for a in alerts}
    assert {"glucose_low", "glucose_high", "tir_low", "bp_high", "doses_missed"} <= cats
    # Nadir 48 (<54) and TIR 48 (<50) are critical, and sort first.
    assert alerts[0].severity == "critical"


def test_alerts_use_precomputed_event_values():
    g = GlucoseRollup(tir_pct=85)
    spine = _cgm([SpineEvent(type="hypo", start=3.0, end=3.5, peak=61)])  # nadir 61 → not severe
    alerts = M.day_alerts(g, spine, [], [_TAKEN])
    low = next(a for a in alerts if a.category == "glucose_low")
    assert low.severity == "attention" and "nadir 61" in low.label and low.t == 3.0


def test_alerts_empty_on_a_clean_day():
    g = GlucoseRollup(tir_pct=90)
    assert M.day_alerts(g, _cgm(), [], [_TAKEN]) == []


def test_alerts_missed_counts_only_missed_not_pending():
    scheduled = DoseMarker(t=22, slot="night", label="N", status="scheduled", taken=False)
    alerts = M.day_alerts(GlucoseRollup(), _cgm(), [], [_TAKEN, scheduled, _MISSED])
    dose_alerts = [a for a in alerts if a.category == "doses_missed"]
    assert len(dose_alerts) == 1 and dose_alerts[0].label == "1 dose missed"


def test_alerts_no_glucose_device():
    alerts = M.day_alerts(GlucoseRollup(), Spine(source=SpineSource.none), [], [])
    assert [a.category for a in alerts] == ["no_glucose"]


if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  ✓ {fn.__name__}")
    print(f"\n{len(fns)} day-view checks passed")
    sys.exit(0)
