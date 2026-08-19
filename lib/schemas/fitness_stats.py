"""Pydantic schemas for fitness statistics reports."""

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class DateRange(BaseModel):
    start: str = Field(..., description="Start date in ISO format")
    end: str = Field(..., description="End date in ISO format")


class ReportMetadata(BaseModel):
    date_range: DateRange
    days_covered: int
    report_type: str
    # Distinct days with any fitness sample; separates a sedentary day from a
    # day the device wasn't worn.
    days_with_data: int = 0


class ActivityDistribution(BaseModel):
    time_of_day: str
    steps: int
    active_energy: float
    active_duration: float
    distance: float = 0
    flights_climbed: int = 0


class PeakActivityTime(BaseModel):
    hour: str
    max_steps: int
    max_active_energy: float
    max_distance: float = 0


class InactivePeriod(BaseModel):
    start_time: str = Field(..., description="Start time of inactivity period")
    end_time: str = Field(..., description="End time of inactivity period")
    inactive_duration: int = Field(..., description="Duration in minutes")


class HourlyStats(BaseModel):
    hour: int
    steps: int
    active_energy: float
    active_duration: float
    distance: float = 0
    flights_climbed: int = 0


class FitnessTrend(BaseModel):
    """This period vs the immediately-preceding equal-length window."""

    previous_steps: int
    previous_active_energy: float
    previous_active_duration: float
    delta_steps: int
    delta_active_energy: float
    delta_active_duration: float


class WorkoutSummary(BaseModel):
    type: str
    session_count: int = 1
    total_duration: float                    # minutes (this session)
    total_energy: float                      # kcal (this session)
    source: str = "app"                      # source_platform from sync, or "app" for manual
    workout_id: Optional[str] = None         # UUID for manual workouts, None for synced
    start_time: Optional[str] = None         # ISO datetime; one entry per session
    end_time: Optional[str] = None           # ISO datetime


class FitnessStats(BaseModel):
    metadata: ReportMetadata
    steps: int
    active_energy: float
    active_duration: float
    average_active_session_duration: float
    distance: float = 0
    flights_climbed: int = 0
    exercise_time: float = 0
    workouts: Optional[List[WorkoutSummary]] = None
    activity_distribution: Optional[Dict[str, ActivityDistribution]] = None
    peak_activity_time: Optional[PeakActivityTime] = None
    inactive_periods: Optional[List[InactivePeriod]] = None
    hourly_stats: Optional[List[HourlyStats]] = None
    trend: Optional[FitnessTrend] = None

    @property
    def start_date(self):
        """Backward compatibility: return start date from metadata."""
        from datetime import datetime
        return datetime.fromisoformat(self.metadata.date_range.start.replace("Z", "+00:00"))

    @property
    def end_date(self):
        """Backward compatibility: return end date from metadata."""
        from datetime import datetime
        return datetime.fromisoformat(self.metadata.date_range.end.replace("Z", "+00:00"))

    @property
    def report_type(self):
        """Backward compatibility: return report type from metadata."""
        return self.metadata.report_type
