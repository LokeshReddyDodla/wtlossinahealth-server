"""Checks for derived meal report logic: post-meal glucose response."""

from datetime import datetime, timedelta

from lib.services.reports.meal.daily_stats import compute_glucose_response

MEAL = datetime(2026, 1, 1, 12, 0)


def _rows(*pairs):
    return [(MEAL + timedelta(minutes=m), g) for m, g in pairs]


def test_none_when_no_post_meal_readings():
    assert compute_glucose_response(MEAL, _rows((-15, 100)), []) is None


def test_excursion_delta_peak_and_time():
    before = _rows((-15, 95), (-5, 100))
    after = _rows((15, 130), (45, 165), (90, 120))
    r = compute_glucose_response(MEAL, before, after)
    assert r["baseline_mgdl"] == 100          # last pre-meal reading
    assert r["peak_mgdl"] == 165
    assert r["delta_mgdl"] == 65
    assert r["time_to_peak_minutes"] == 45
    assert r["returned_to_baseline"] is False  # 120 > 100 + 15


def test_baseline_falls_back_to_first_after():
    r = compute_glucose_response(MEAL, [], _rows((15, 130), (45, 150)))
    assert r["baseline_mgdl"] == 130
    assert r["delta_mgdl"] == 20


def test_returned_to_baseline():
    r = compute_glucose_response(MEAL, _rows((-5, 100)), _rows((15, 140), (60, 110)))
    assert r["returned_to_baseline"] is True   # 110 <= 100 + 15, after the peak


if __name__ == "__main__":
    test_none_when_no_post_meal_readings()
    test_excursion_delta_peak_and_time()
    test_baseline_falls_back_to_first_after()
    test_returned_to_baseline()
    print("ok")
