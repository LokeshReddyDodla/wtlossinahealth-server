from datetime import datetime
from typing import Dict, Optional

from pydantic import BaseModel


class SleepStats(BaseModel):
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    date: Optional[datetime] = None  # For daily stats
    total_sleep_duration: float  # Total sleep in minutes/hours
    sleep_type_distribution: Dict[str, float]  # % of each sleep type
    sleep_start_time: Optional[datetime] = None
    sleep_end_time: Optional[datetime] = None
