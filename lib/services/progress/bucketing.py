"""Pure time-bucketing for progress trends — no I/O, so it self-checks.

Daily points collapse to weekly (Monday-anchored) or monthly (1st-anchored)
buckets by mean. Order-independent: non-consecutive days bucket correctly, so a
patient with gaps still trends.
"""

from datetime import date, timedelta
from statistics import mean

# range key → months of history; ≤3 months trends weekly, longer trends monthly.
_MONTHS = {"1M": 1, "3M": 3, "6M": 6, "1Y": 12}


def window_for(range_key: str) -> tuple[int, str]:
    months = _MONTHS[range_key]
    return months, "weekly" if months <= 3 else "monthly"


def months_ago(d: date, n: int) -> date:
    m = d.month - n
    y = d.year + (m - 1) // 12
    m = (m - 1) % 12 + 1
    return date(y, m, min(d.day, 28))


def bucket_key(d: date, resolution: str) -> date:
    if resolution == "weekly":
        return d - timedelta(days=d.weekday())
    return d.replace(day=1)


def bucketize(points, resolution: str) -> list[tuple[str, float]]:
    """(date, value) pairs → [(bucket_iso, mean_value)] sorted ascending."""
    buckets: dict[date, list[float]] = {}
    for d, v in points:
        if v is None:
            continue
        buckets.setdefault(bucket_key(d, resolution), []).append(float(v))
    return [(k.isoformat(), round(mean(vs), 2)) for k, vs in sorted(buckets.items())]


if __name__ == "__main__":
    assert window_for("1M") == (1, "weekly")
    assert window_for("1Y") == (12, "monthly")
    assert months_ago(date(2026, 3, 15), 6) == date(2025, 9, 15)
    assert months_ago(date(2026, 1, 31), 1) == date(2025, 12, 28)  # day clamps to 28
    assert bucket_key(date(2026, 1, 7), "weekly").weekday() == 0  # Wed → Monday
    assert bucket_key(date(2026, 1, 20), "monthly") == date(2026, 1, 1)
    pts = [(date(2026, 1, 1), 10), (date(2026, 1, 2), 20),
           (date(2026, 2, 1), 30), (date(2026, 1, 15), None)]
    monthly = dict(bucketize(pts, "monthly"))
    assert monthly == {"2026-01-01": 15.0, "2026-02-01": 30.0}, monthly
    assert len(bucketize(pts, "weekly")) == 2  # Jan1/2 same week, Feb1 another
    print("bucketing self-check ok")
