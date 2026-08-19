"""Checks for derived fitness report logic: trend gate + deltas."""


def _fitness_trend(row, prev):
    """Mirror of the processor trend logic. `row` = current summary tuple
    (steps, active_energy, active_duration, ...); `prev` = same for the previous
    window (or None). Returns None unless the previous window had activity."""
    if not (prev and (prev[0] or prev[1])):
        return None
    prev_steps = int(prev[0] or 0)
    prev_energy = float(prev[1] or 0.0)
    prev_dur = float(prev[2] or 0.0)
    return {
        "delta_steps": int(row[0]) - prev_steps,
        "delta_active_energy": row[1] - prev_energy,
        "delta_active_duration": row[2] - prev_dur,
    }


def test_trend_none_when_no_previous_data():
    assert _fitness_trend((5000, 300.0, 45), None) is None
    # An all-zero previous window (no wear) is treated as no baseline.
    assert _fitness_trend((5000, 300.0, 45), (0, 0.0, 0)) is None


def test_trend_deltas():
    t = _fitness_trend((5000, 300.0, 45), (4000, 250.0, 30))
    assert t == {
        "delta_steps": 1000,
        "delta_active_energy": 50.0,
        "delta_active_duration": 15.0,
    }


def test_trend_negative_delta():
    t = _fitness_trend((3000, 200.0, 20), (4000, 250.0, 30))
    assert t["delta_steps"] == -1000
    assert t["delta_active_duration"] == -10.0


if __name__ == "__main__":
    test_trend_none_when_no_previous_data()
    test_trend_deltas()
    test_trend_negative_delta()
    print("ok")
