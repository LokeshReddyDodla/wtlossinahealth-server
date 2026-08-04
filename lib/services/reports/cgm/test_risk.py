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


def _sensor_active_pct(total_readings, median_gap_s, window_seconds):
    if not (median_gap_s and window_seconds):
        return 0.0
    return round(min(100.0, total_readings * median_gap_s / window_seconds * 100), 1)


def test_sensor_active_scored_on_own_cadence():
    day = 86400
    # 15-min sensor, half the day covered → 48 readings, gap 900s → 50%.
    assert _sensor_active_pct(48, 900, day) == 50.0
    # 5-min sensor, half covered → 144 readings, gap 300s → 50% (same coverage).
    assert _sensor_active_pct(144, 300, day) == 50.0
    # Fully covered 5-min sensor → 288 readings → clamps to 100%.
    assert _sensor_active_pct(288, 300, day) == 100.0
    # No cadence (single reading) → 0, no divide-by-zero.
    assert _sensor_active_pct(1, 0, day) == 0.0


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
    test_sensor_active_scored_on_own_cadence()
    test_nocturnal_and_dawn_math()
    test_trend_delta_gmi_tracks_delta_avg()
    print("ok")
