"""Pure-logic checks for the day-view mappers and spine degradation.

No database — every function under test takes plain dicts/lists. The DB paths
(repository) and the gather orchestration (resolver) are exercised separately.
"""

from datetime import datetime

from lib.schemas.day_view import (
    DoseMarker,
    GlucoseRollup,
    Spine,
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


# ── clinical alerts (2019 International Consensus targets) ────────────────────

_TAKEN = DoseMarker(t=8, slot="morning", label="M", status="taken", taken=True)
_MISSED = DoseMarker(t=20, slot="evening", label="E", status="missed", taken=False)


def _cgm(source: SpineSource = SpineSource.cgm) -> Spine:
    return Spine(source=source, unit="mg/dL", band=(70.0, 180.0))


def _roll(bands, tir=None, cv=None, low=None, high=None,
          tir_preg=None, tbr_54_63=None, tar_140=None) -> GlucoseRollup:
    # bands = [<54, 54-70, 70-180, 180-250, >250] percentages
    return GlucoseRollup(tir_pct=tir, cv_pct=cv, low_mgdl=low, high_mgdl=high, bands=bands,
                         tir_preg_pct=tir_preg, tbr_54_63_pct=tbr_54_63, tar_140_pct=tar_140)


def test_target_tier_from_profile():
    assert M.select_glucose_targets(40, False).tier == "standard"
    assert M.select_glucose_targets(72, False).tier == "older_high_risk"
    assert M.select_glucose_targets(30, True).tier == "pregnancy"


def test_alerts_flag_a_bad_day():
    g = _roll([3, 5, 40, 22, 30], tir=40, cv=44, low=45, high=305)
    bp = [VitalMarker(t=14.0, systolic=148, diastolic=96)]
    alerts = M.day_alerts(g, _cgm(), bp, [_MISSED, _TAKEN], M._STANDARD)
    cats = {a.category for a in alerts}
    assert {"tbr_l2", "tar_high", "tir_low", "glucose_cv", "bp_high", "doses_missed"} <= cats
    assert alerts[0].severity == "critical"  # serious lows sort first


def test_alerts_read_precomputed_percentages():
    g = _roll([0, 6, 84, 8, 2], tir=84, low=58)  # 6% time <70 breaches the 4% target
    alerts = M.day_alerts(g, _cgm(), [], [_TAKEN], M._STANDARD)
    low = next(a for a in alerts if a.category == "tbr_l1")
    assert low.severity == "attention" and "6% of day below 70" in low.label and "low 58" in low.label


def test_alerts_within_consensus_targets_are_silent():
    g = _roll([0, 2, 95, 3, 0], tir=95, cv=30)  # every band inside standard targets
    assert M.day_alerts(g, _cgm(), [], [_TAKEN], M._STANDARD) == []


def test_older_tier_flags_tighter_lows():
    g = _roll([0, 2, 96, 2, 0], tir=96, cv=30)  # 2% <70: fine for standard, breaches older (<1%)
    assert M.day_alerts(g, _cgm(), [], [_TAKEN], M._STANDARD) == []
    older = M.day_alerts(g, _cgm(), [], [_TAKEN], M._OLDER)
    assert [a.category for a in older] == ["tbr_l1"]


def test_pregnancy_uses_tighter_63_140_targets():
    # Adult bands read in-range, but the tighter pregnancy range flags the day.
    g = _roll([0, 2, 83, 15, 0], tir=83, tir_preg=60, tbr_54_63=2, tar_140=30)
    assert M.day_alerts(g, _cgm(), [], [_TAKEN], M._STANDARD) == []
    preg = M.day_alerts(g, _cgm(), [], [_TAKEN], M._PREGNANCY)
    assert {a.category for a in preg} == {"tir_low", "tar_high"}
    assert "above 140" in next(a for a in preg if a.category == "tar_high").label


def test_pregnancy_needs_report_refresh_when_bands_absent():
    g = _roll([0, 2, 83, 15, 0], tir=83)  # report without the 63-140 bands
    alerts = M.day_alerts(g, _cgm(), [], [_TAKEN], M._PREGNANCY)
    assert [a.category for a in alerts] == ["glucose_targets_unsupported"]
    assert alerts[0].severity == "info"


def test_pregnancy_band_and_tir_follow_profile():
    assert M.select_spine(_CGM_REP, _SMBG, M._PREGNANCY.in_range).band == (63.0, 140.0)
    assert M.select_spine(_CGM_REP, _SMBG).band == (70.0, 180.0)
    rep = {"cgm_range_stats": {
        "below_54_percent": 1, "below_70_above_54_percent": 3, "in_target_70_180_percent": 80,
        "above_180_below_250_percent": 10, "above_250_percent": 6,
        "below_63_above_54_percent": 2, "in_target_63_140_percent": 55, "above_140_percent": 42,
    }}
    std = M.glucose_rollup(rep)
    preg = M.glucose_rollup(rep, preg=True)
    # bands describe the same window as tir_pct: 5 standard, 4 pregnancy.
    assert std.tir_pct == 80 and len(std.bands) == 5
    assert preg.tir_pct == 55 and preg.bands == [1.0, 2.0, 55.0, 42.0]


def test_pregnancy_rollup_has_no_bands_before_report_refresh():
    rep = {"cgm_range_stats": {"in_target_70_180_percent": 80, "below_54_percent": 1}}
    roll = M.glucose_rollup(rep, preg=True)
    assert roll.tir_pct is None and roll.bands is None


def test_hyper_excursions_at_pregnancy_threshold():
    readings = [
        {"device_timestamp": "2026-08-06T08:00:00", "glucose_mgdl": 120},  # below 140
        {"device_timestamp": "2026-08-06T08:15:00", "glucose_mgdl": 150},
        {"device_timestamp": "2026-08-06T08:30:00", "glucose_mgdl": 165},
        {"device_timestamp": "2026-08-06T08:45:00", "glucose_mgdl": 130},  # ends the run
        {"device_timestamp": "2026-08-06T09:00:00", "glucose_mgdl": 145},  # lone point, no run
    ]
    ev = M.hyper_excursions(readings, threshold=140)
    assert len(ev) == 1
    assert ev[0]["peak_glucose_mgdl"] == 165 and ev[0]["duration_minutes"] == 15.0


def test_bp_crisis_outranks_high():
    alerts = M.day_alerts(GlucoseRollup(), _cgm(), [VitalMarker(t=10, systolic=184, diastolic=110)], [], M._STANDARD)
    bp = next(a for a in alerts if a.category == "bp_high")
    assert bp.severity == "critical" and "crisis" in bp.label.lower()


def test_alerts_missed_counts_only_missed_not_pending():
    scheduled = DoseMarker(t=22, slot="night", label="N", status="scheduled", taken=False)
    alerts = M.day_alerts(_roll([0, 0, 100, 0, 0]), _cgm(), [], [_TAKEN, scheduled, _MISSED], M._STANDARD)
    dose_alerts = [a for a in alerts if a.category == "doses_missed"]
    assert len(dose_alerts) == 1 and dose_alerts[0].label == "1 dose missed"


def test_alerts_no_glucose_device():
    alerts = M.day_alerts(GlucoseRollup(), Spine(source=SpineSource.none), [], [], M._STANDARD)
    assert [a.category for a in alerts] == ["no_glucose"]


if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  ✓ {fn.__name__}")
    print(f"\n{len(fns)} day-view checks passed")
    sys.exit(0)
