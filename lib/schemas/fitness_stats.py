from datetime import date, datetime
from typing import Dict, List, Optional

from pydantic import BaseModel

from rest_server.response_models import SuccessResponse


class FitnessActivityDistribution(BaseModel):
    time_of_day: str
    steps: int
    active_energy: float
    active_duration: float


class FitnessPeakActivityTime(BaseModel):
    hour: str
    max_steps: int
    max_active_energy: float


class FitnessInactivePeriod(BaseModel):
    start_time: datetime  # Start time of the inactivity period
    end_time: datetime  # End time of the inactivity period
    inactive_duration: int  # Duration in minutes


class FitnessWeekOverWeekComparison(BaseModel):
    steps_diff: int
    active_energy_diff: float
    active_duration_diff: float


class FitnessHourlyStats(BaseModel):
    hour: int
    steps: int
    active_energy: float
    active_duration: float


class FitnessStats(BaseModel):
    steps: int
    active_energy: float
    active_duration: float
    average_active_session_duration: float
    activity_distribution: Optional[Dict[str, FitnessActivityDistribution]] = (
        None
    )
    peak_activity_time: Optional[FitnessPeakActivityTime] = None
    inactive_periods: Optional[List[FitnessInactivePeriod]] = None
    hourly_stats: Optional[List[FitnessHourlyStats]] = None
    start_date: datetime
    end_date: datetime
