from datetime import datetime
from typing import Any, Optional

import pytz


def convert_milliseconds_to_datetime(timestamp_ms: int, timezone_str: str) -> datetime:
    timestamp_s = timestamp_ms / 1000
    naive_dt = datetime.fromtimestamp(timestamp_s)
    utc_dt = naive_dt.replace(tzinfo=pytz.utc)
    target_timezone = pytz.timezone(timezone_str)
    localized_dt = utc_dt.astimezone(target_timezone)
    return localized_dt


def parse_datetime(value: Any) -> Optional[datetime]:
    """Parse various datetime formats into datetime object.
    
    Handles datetime objects, ISO format strings, and bytes.
    """
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, bytes):
        value = value.decode()
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return None


def normalize_to_date_iso(dt: Any) -> str:
    """Normalize datetime to date-only (midnight) ISO format for comparison.
    
    Converts any datetime-like value to ISO format with time set to 00:00:00.
    Useful for comparing dates stored in MongoDB (which normalize to midnight)
    with incoming timestamps that may have specific times.
    """
    if isinstance(dt, datetime):
        return dt.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()

    parsed = parse_datetime(dt)
    if parsed:
        return parsed.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()

    return str(dt)