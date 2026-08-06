"""Pure-logic checks for the day-view mappers and spine degradation.

No database — every function under test takes plain dicts/lists. The DB paths
(repository) and the gather orchestration (resolver) are exercised separately.
"""

from lib.schemas.day_view import SpineSource
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
_HR = [(0.0, 56.0), (12.0, 72.0)]


# ── spine degradation ────────────────────────────────────────────────────────

def test_spine_prefers_cgm():
    spine = M.select_spine(_CGM_REP, _SMBG, _HR)
    assert spine.source is SpineSource.cgm
    assert len(spine.points) == 2
    assert {e.type for e in spine.events} == {"hypo", "hyper"}
    assert spine.band == (70.0, 180.0)


def test_spine_falls_to_smbg_without_cgm():
    spine = M.select_spine(None, _SMBG, _HR)
    assert spine.source is SpineSource.smbg
    assert spine.points == _SMBG
    assert not spine.events  # dots carry no excursion spans


def test_spine_falls_to_hr_without_glucose():
    spine = M.select_spine(None, [], _HR)
    assert spine.source is SpineSource.hr
    assert spine.unit == "bpm"
    assert spine.band == (60.0, 100.0)


def test_spine_none_when_nothing():
    spine = M.select_spine(None, [], [])
    assert spine.source is SpineSource.none
    assert spine.points == []


def test_cgm_with_empty_readings_is_not_a_cgm_spine():
    # A report present but curve-less must not win the spine over SMBG.
    spine = M.select_spine({"cgm_summary_stats": {"average_glucose_mgdl": 130}}, _SMBG, _HR)
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


if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  ✓ {fn.__name__}")
    print(f"\n{len(fns)} day-view checks passed")
    sys.exit(0)
