"""Self-checks for the pure night-stats derivations. Run: python -m
lib.services.reports.sleep.test_sleep"""

from lib.services.reports.sleep.night_stats import derive


def test_duration_uses_asleep_only():
    # total/avg/longest/shortest come straight from asleep time, not the
    # in-bed envelope — the double-count bug this replaced.
    d = derive(
        nights=4, total_asleep=1600, avg_asleep=400, longest=460, shortest=360,
        bedtime_sd=20, wake_sd=30, days_covered=7,
    )["duration"]
    assert d["total_duration"] == 1600
    assert d["average_duration"] == 400
    assert d["longest_sleep"] == 460
    assert d["shortest_sleep"] == 360
    # per-day averages over the whole window, including nights with no data.
    assert d["per_day_average_duration"] == round(1600 / 7, 1)


def test_debt_vs_recommended_minimum():
    c = derive(4, 1600, 400, 460, 360, 20, 30, 7)["consistency"]
    # 420 (7h) - 400 asleep = 20 min shortfall.
    assert c["sleep_debt_minutes"] == 20
    # No debt when the average clears the minimum.
    assert derive(4, 1920, 480, 500, 460, 20, 30, 7)["consistency"]["sleep_debt_minutes"] == 0


def test_consistency_score_scales_with_variability():
    perfect = derive(5, 2000, 400, 400, 400, 0, 0, 7)["consistency"]
    assert perfect["consistency_score"] == 100
    # avg SD of 60 min -> 50; 120+ -> floored at 0.
    assert derive(5, 2000, 400, 400, 400, 60, 60, 7)["consistency"]["consistency_score"] == 50
    assert derive(5, 2000, 400, 400, 400, 200, 200, 7)["consistency"]["consistency_score"] == 0


def test_variability_needs_enough_nights():
    # Two nights can't establish a pattern -> no score, no variability.
    c = derive(2, 800, 400, 420, 380, 5, 5, 7)["consistency"]
    assert c["consistency_score"] is None
    assert c["bedtime_variability_minutes"] is None
    assert c["nights_tracked"] == 2  # count is still reported


def test_no_asleep_data_is_null_not_zero():
    c = derive(0, 0, None, None, None, None, None, 7)["consistency"]
    assert c["average_nightly_sleep_minutes"] is None
    assert c["sleep_debt_minutes"] is None  # never claim full debt on missing data


if __name__ == "__main__":
    test_duration_uses_asleep_only()
    test_debt_vs_recommended_minimum()
    test_consistency_score_scales_with_variability()
    test_variability_needs_enough_nights()
    test_no_asleep_data_is_null_not_zero()
    print("all sleep night-stats checks passed")
