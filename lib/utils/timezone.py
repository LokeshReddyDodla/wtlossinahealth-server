from datetime import datetime, date, time
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def get_ist_now() -> datetime:
    """Returns current time in Asia/Kolkata (tz-aware)."""
    return datetime.now(tz=IST)


def get_ist_day_bounds(target_date: date) -> tuple[datetime, datetime]:
    """
    Returns start and end datetime for a given date in IST.
    """
    start = datetime.combine(target_date, time.min, tzinfo=IST)
    end = datetime.combine(target_date, time.max, tzinfo=IST)
    return start, end
