"""Self-checks for the per-night reconciliation math (wearable + manual). Run:
python -m lib.services.reports.sleep.test_sleep"""

from lib.services.reports.sleep.night_stats import (
    _clock_to_min_since_noon,
    derive_nights,
    recommended_minimum_for_age,
)


def _w(asleep, bed=None, wake=None):
    return {"asleep": asleep, "bed_min": bed, "wake_min": wake, "source": "wearable"}


def _m(asleep, quality=None, bed=None, wake=None):
    return {
        "asleep": asleep, "bed_min": bed, "wake_min": wake,
        "quality": quality, "source": "manual",
    }


def test_duration_uses_asleep_only():
    nights = [_w(400, 700, 60), _w(420, 690, 70), _w(380, 710, 50), _w(460, 680, 80)]
    d = derive_nights(nights, 8, 120, 7)["duration"]
    assert d["total_duration"] == 1660
    assert d["average_duration"] == 415
    assert d["longest_sleep"] == 460
    assert d["shortest_sleep"] == 380
    assert d["per_day_average_duration"] == round(1660 / 7, 1)


def test_debt_vs_recommended_minimum():
    c = derive_nights([_w(400, 700, 60), _w(400, 690, 70), _w(400, 710, 50)], 0, 0, 7)[
        "consistency"
    ]
    assert c["sleep_debt_minutes"] == 20  # 420 - 400
    assert derive_nights([_w(480), _w(480), _w(480)], 0, 0, 7)["consistency"][
        "sleep_debt_minutes"
    ] == 0


def test_consistency_score_scales_with_variability():
    perfect = derive_nights([_w(400, 700, 60) for _ in range(5)], 0, 0, 7)["consistency"]
    assert perfect["consistency_score"] == 100
    # bed pstdev 60, wake pstdev 60 -> avg 60 -> score 50.
    spread = [_w(400, 640, 0), _w(400, 760, 120), _w(400, 640, 0), _w(400, 760, 120)]
    assert derive_nights(spread, 0, 0, 7)["consistency"]["consistency_score"] == 50


def test_variability_needs_enough_nights():
    c = derive_nights([_w(400, 700, 60), _w(400, 690, 70)], 0, 0, 7)["consistency"]
    assert c["consistency_score"] is None
    assert c["bedtime_variability_minutes"] is None
    assert c["nights_tracked"] == 2


def test_no_data_is_null_not_zero():
    r = derive_nights([], 0, 0, 7)
    assert r["consistency"]["average_nightly_sleep_minutes"] is None
    assert r["consistency"]["sleep_debt_minutes"] is None
    assert r["fragmentation"]["average_awakenings"] is None


def test_fragmentation_over_wearable_nights_only():
    # 3 wearable + 1 manual; awakenings/WASO divide by wearable nights only.
    nights = [
        _w(400, 700, 60), _w(400, 690, 70), _w(400, 710, 50),
        _m(360, quality=4, bed=680, wake=80),
    ]
    r = derive_nights(nights, total_awakenings=6, total_waso=90, days_covered=7)
    assert r["fragmentation"]["average_awakenings"] == 2.0  # 6 / 3 wearable
    assert r["fragmentation"]["average_waso_minutes"] == 30.0
    c = r["consistency"]
    assert c["nights_tracked"] == 4
    assert c["wearable_nights"] == 3
    assert c["manual_nights"] == 1
    assert c["subjective_quality"] == 4.0
    assert r["duration"]["total_duration"] == 1560  # manual night counts too


def test_manual_only_report():
    # No wearable: duration/consistency/quality from check-ins; fragmentation null.
    nights = [_m(390, 3, 650, 30), _m(420, 4, 660, 40), _m(450, 5, 640, 20)]
    r = derive_nights(nights, 0, 0, 7)
    assert r["fragmentation"]["average_awakenings"] is None
    assert r["consistency"]["wearable_nights"] == 0
    assert r["consistency"]["manual_nights"] == 3
    assert r["consistency"]["subjective_quality"] == 4.0  # (3+4+5)/3
    assert r["duration"]["average_duration"] == 420


def test_recommended_minimum_by_age():
    assert recommended_minimum_for_age(15) == 480  # teen: 8h floor
    assert recommended_minimum_for_age(30) == 420  # adult: 7h
    assert recommended_minimum_for_age(70) == 420  # older adult: 7h
    assert recommended_minimum_for_age(None) == 420  # unknown -> adult default


def test_debt_uses_age_based_minimum():
    # A teen sleeping 7h is in debt against the 8h floor.
    c = derive_nights([_w(420), _w(420), _w(420)], 0, 0, 7, recommended_min=480)[
        "consistency"
    ]
    assert c["recommended_min_minutes"] == 480
    assert c["sleep_debt_minutes"] == 60  # 480 - 420


def test_clock_parsing_wraps_around_midnight():
    assert _clock_to_min_since_noon("23:00") == 660
    assert _clock_to_min_since_noon("01:00") == 780  # after midnight, still one night
    assert _clock_to_min_since_noon("07:00") == 1140
    assert _clock_to_min_since_noon(None) is None
    assert _clock_to_min_since_noon("bad") is None


if __name__ == "__main__":
    test_duration_uses_asleep_only()
    test_debt_vs_recommended_minimum()
    test_consistency_score_scales_with_variability()
    test_variability_needs_enough_nights()
    test_no_data_is_null_not_zero()
    test_fragmentation_over_wearable_nights_only()
    test_manual_only_report()
    test_recommended_minimum_by_age()
    test_debt_uses_age_based_minimum()
    test_clock_parsing_wraps_around_midnight()
    print("all sleep reconciliation checks passed")
