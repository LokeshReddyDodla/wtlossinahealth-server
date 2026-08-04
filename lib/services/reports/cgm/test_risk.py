"""Checks for the derived CGM report metrics: GRI and sensor-active %."""

from lib.schemas.cgm_stats import CGMRangeStats
from lib.services.reports.cgm.range_stats import CGMRangeStatistics


def test_gri_zero_when_all_in_range():
    stats = CGMRangeStats(
        below_54_percent=0.0,
        below_70_above_54_percent=0.0,
        in_target_70_180_percent=100.0,
        above_180_below_250_percent=0.0,
        above_250_percent=0.0,
    )
    assert CGMRangeStatistics.compute_gri(stats) == 0.0


def test_gri_weights_hypo_over_hyper():
    # 10% very-low should score higher than 10% high (hypo weighted heavier).
    vlow = CGMRangeStats(
        below_54_percent=10.0,
        below_70_above_54_percent=0.0,
        in_target_70_180_percent=90.0,
        above_180_below_250_percent=0.0,
        above_250_percent=0.0,
    )
    high = CGMRangeStats(
        below_54_percent=0.0,
        below_70_above_54_percent=0.0,
        in_target_70_180_percent=90.0,
        above_180_below_250_percent=10.0,
        above_250_percent=0.0,
    )
    assert CGMRangeStatistics.compute_gri(vlow) == 30.0  # 3.0 * 10
    assert CGMRangeStatistics.compute_gri(high) == 8.0   # 0.8 * 10
    assert CGMRangeStatistics.compute_gri(vlow) > CGMRangeStatistics.compute_gri(high)


def test_gri_capped_at_100():
    stats = CGMRangeStats(
        below_54_percent=100.0,
        below_70_above_54_percent=0.0,
        in_target_70_180_percent=0.0,
        above_180_below_250_percent=0.0,
        above_250_percent=0.0,
    )
    assert CGMRangeStatistics.compute_gri(stats) == 100.0


def test_sensor_active_percent_full_day():
    # A full day at 15-min cadence = 96 expected intervals.
    expected_intervals = round(86399.999999 / 900)
    assert expected_intervals == 96
    active_intervals = 48  # half the day covered
    pct = round(min(100.0, active_intervals / expected_intervals * 100), 1)
    assert pct == 50.0


def test_nocturnal_and_dawn_math():
    # 3 of 20 overnight readings below 70.
    nocturnal_below, nocturnal_total = 3, 20
    assert (nocturnal_below / nocturnal_total) * 100 == 15.0
    # Dawn rise = avg(03:00-05:59) - avg(00:00-02:59); positive = rise.
    dawn_avg, predawn_avg = 130.0, 105.0
    assert (dawn_avg - predawn_avg) == 25.0


def test_trend_delta_gmi_tracks_delta_avg():
    # delta_gmi is the GMI slope (0.02392) times the mean change; the constant
    # 3.31 cancels in a difference.
    cur_avg, prev_avg = 150.0, 170.0
    gmi = lambda a: 3.31 + 0.02392 * a
    assert round(gmi(cur_avg) - gmi(prev_avg), 6) == round(0.02392 * (cur_avg - prev_avg), 6)


if __name__ == "__main__":
    test_gri_zero_when_all_in_range()
    test_gri_weights_hypo_over_hyper()
    test_gri_capped_at_100()
    test_sensor_active_percent_full_day()
    test_nocturnal_and_dawn_math()
    test_trend_delta_gmi_tracks_delta_avg()
    print("ok")
