from datetime import datetime, date
from pydantic import BaseModel
from typing import List, Optional, Dict


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
    inactive_duration: int  # Duration in minutes


class FitnessWeekOverWeekComparison(BaseModel):
    steps_diff: int
    active_energy_diff: float
    active_duration_diff: float


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


class FitnessDailyStats(FitnessBaseStats):
    date: date


class FitnessWeeklyStats(FitnessBaseStats):
    week_number: int
    week_over_week_comparison: Optional[FitnessWeekOverWeekComparison] = None


class FitnessMonthlyStats(FitnessBaseStats):
    month: str
    week_over_week_comparison: Optional[FitnessWeekOverWeekComparison] = None


class FitnessHourlyStats(BaseModel):
    hour: str
    steps: int
    active_energy: float
    active_duration: float


class FitnessSummaryStats(FitnessBaseStats):
    pass


class FitnessStatsResponse(BaseModel):
    patient_id: str
    summary: FitnessSummaryStats
    daily_stats: Optional[List[FitnessDailyStats]] = None
    weekly_stats: Optional[List[FitnessWeeklyStats]] = None
    monthly_stats: Optional[List[FitnessMonthlyStats]] = None
    hourly_stats: Optional[List[FitnessHourlyStats]] = None
