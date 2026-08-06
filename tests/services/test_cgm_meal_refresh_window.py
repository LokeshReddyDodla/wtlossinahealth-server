"""The meal-report refresh window (CGM sync → which days to regenerate).

Pure date math — no DB. Guards the delta-scoping fix: a sync must refresh only
the days that received new CGM, not the patient's whole history.
"""

from datetime import date, datetime, timedelta

import pandas as pd

from lib.services.cgm_upload_service import (
    _FIRST_CONNECT_BACKFILL_DAYS,
    CGMUploadService,
)

W = CGMUploadService._meal_refresh_window


def test_delta_window_starts_one_day_before_prior_frontier():
    prior = datetime(2026, 8, 4, 20, 0)      # newest reading we already had
    end = datetime(2026, 8, 6, 17, 5)        # newest reading in this upload
    assert W(prior, end) == (date(2026, 8, 3), date(2026, 8, 6))  # −1 day lead-in


def test_regular_sync_is_a_handful_of_days_not_all_history():
    prior = datetime(2026, 8, 6, 8, 0)
    end = datetime(2026, 8, 6, 17, 0)
    start, stop = W(prior, end)
    assert (stop - start).days == 1  # Aug 5 → Aug 6, not 500 days


def test_first_connect_caps_to_recent_window():
    end = datetime(2026, 8, 6, 12, 0)
    start, stop = W(None, end)          # no prior frontier
    assert stop == date(2026, 8, 6)
    assert start == (end - timedelta(days=_FIRST_CONNECT_BACKFILL_DAYS)).date()
    assert (stop - start).days == _FIRST_CONNECT_BACKFILL_DAYS


def test_disconnect_then_reconnect_backfills_the_gap():
    prior = datetime(2026, 7, 20, 9, 0)  # last reading two+ weeks ago
    end = datetime(2026, 8, 6, 9, 0)
    start, stop = W(prior, end)
    assert start == date(2026, 7, 19) and stop == date(2026, 8, 6)


def test_no_new_data_is_a_noop():
    assert W(None, None) is None
    assert W(None, pd.NaT) is None
    # Frontier ahead of this upload (nothing newer) → nothing to do.
    assert W(datetime(2026, 8, 10), datetime(2026, 8, 6)) is None


def test_accepts_pandas_timestamp_end():
    prior = datetime(2026, 8, 4, 20, 0)
    end = pd.Timestamp("2026-08-06 17:05:00")
    assert W(prior, end) == (date(2026, 8, 3), date(2026, 8, 6))


if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  ✓ {fn.__name__}")
    print(f"\n{len(fns)} meal-refresh-window checks passed")
    sys.exit(0)
