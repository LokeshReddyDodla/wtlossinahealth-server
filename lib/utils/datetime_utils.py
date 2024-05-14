from datetime import datetime
import pytz

def convert_milliseconds_to_datetime(timestamp_ms: int, timezone_str: str) -> datetime:
    timestamp_s = timestamp_ms / 1000
    naive_dt = datetime.fromtimestamp(timestamp_s)
    utc_dt = naive_dt.replace(tzinfo=pytz.utc)
    target_timezone = pytz.timezone(timezone_str)
    localized_dt = utc_dt.astimezone(target_timezone)
    return localized_dt