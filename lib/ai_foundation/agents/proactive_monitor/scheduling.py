"""
Timezone-aware scan scheduling for the Proactive Monitor.

Provides utilities to determine whether a patient is within their local
scan window (7 AM - 10 PM).  Defaults to Asia/Kolkata when the patient's
timezone is unknown (most patients are in India).
"""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# Scan window: only scan patients between these local hours
SCAN_WINDOW_START = 7   # 7:00 AM local
SCAN_WINDOW_END = 22    # 10:00 PM local

# Default timezone when patient profile doesn't specify one
DEFAULT_TIMEZONE = "Asia/Kolkata"


def is_within_scan_window(
    tz_name: str | None = None,
    *,
    now: datetime | None = None,
) -> bool:
    """Check if it's between 7 AM and 10 PM in the given timezone.

    Parameters
    ----------
    tz_name:
        IANA timezone string (e.g. ``"Asia/Kolkata"``).
        Falls back to :data:`DEFAULT_TIMEZONE` when *None* or invalid.
    now:
        Optional override for current time (useful for testing).
        When not provided, ``datetime.now(patient_tz)`` is used.

    Returns
    -------
    bool
        ``True`` if the local hour is in ``[SCAN_WINDOW_START, SCAN_WINDOW_END)``.
    """
    try:
        tz = ZoneInfo(tz_name or DEFAULT_TIMEZONE)
    except (KeyError, TypeError):
        logger.debug("Invalid timezone %r, using default %s", tz_name, DEFAULT_TIMEZONE)
        tz = ZoneInfo(DEFAULT_TIMEZONE)

    local_now = now or datetime.now(tz)
    if local_now.tzinfo is None:
        raise ValueError("now must be timezone-aware; got naive datetime")

    # Convert to the target timezone if it differs
    local_now = local_now.astimezone(tz)
    return SCAN_WINDOW_START <= local_now.hour < SCAN_WINDOW_END
