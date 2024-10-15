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
    hour: str
    steps: int
    active_energy: float
    active_duration: float


class FitnessBaseStats(BaseModel):
    steps: int
    active_energy: float
    active_duration: float
    average_active_session_duration: float
    activity_distribution: Optional[Dict[str, FitnessActivityDistribution]] = (
        None
    )
    peak_activity_time: Optional[FitnessPeakActivityTime] = None
    inactive_periods: Optional[List[FitnessInactivePeriod]] = None
    from_date: date
    to_date: date


class FitnessDailyStats(FitnessBaseStats):
    date: date
    hourly_stats: Optional[List[FitnessHourlyStats]] = None


class FitnessWeeklyStats(FitnessBaseStats):
    week_number: int
    daily_stats: Optional[List[FitnessDailyStats]] = None


class FitnessMonthlyStats(FitnessBaseStats):
    month: str

    daily_stats: Optional[List[FitnessDailyStats]] = None
    weekly_stats: Optional[List[FitnessWeeklyStats]] = None


class FitnessSummaryStats(FitnessBaseStats):
    pass


class CompleteFitnessReport(BaseModel):
    patient_id: str
    summary: FitnessBaseStats
    daily_stats: Optional[List[FitnessDailyStats]] = None
    weekly_stats: Optional[List[FitnessWeeklyStats]] = None
    monthly_stats: Optional[List[FitnessMonthlyStats]] = None
