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


class SummaryMetrics(BaseModel):
    steps: int
    active_energy: float
    active_duration: float
    average_active_session_duration: float


class FitnessSummary(BaseModel):
    metrics: SummaryMetrics


class ActivityDistribution(BaseModel):
    time_of_day: str
    steps: int
    active_energy: float
    active_duration: float


class ActivityDistributionBreakdown(BaseModel):
    by_time_of_day: Dict[str, ActivityDistribution] = Field(
        default_factory=dict, description="Activity distribution by time of day"
    )


class PeakActivityTime(BaseModel):
    hour: str
    max_steps: int
    max_active_energy: float


class InactivePeriod(BaseModel):
    start_time: str = Field(..., description="Start time of inactivity period")
    end_time: str = Field(..., description="End time of inactivity period")
    inactive_duration: int = Field(..., description="Duration in minutes")


class HourlyStats(BaseModel):
    hour: int
    steps: int
    active_energy: float
    active_duration: float


class ActivityBreakdown(BaseModel):
    peak_activity_time: Optional[PeakActivityTime] = None
    inactive_periods: Optional[List[InactivePeriod]] = None
    hourly_stats: Optional[List[HourlyStats]] = None


class FitnessReport(BaseModel):
    metadata: ReportMetadata
    summary: FitnessSummary
    breakdowns: ActivityDistributionBreakdown
    activity: ActivityBreakdown


class FitnessWeekOverWeekComparison(BaseModel):
    steps_diff: int
    active_energy_diff: float
    active_duration_diff: float


class FitnessStats(BaseModel):
    metadata: ReportMetadata
    steps: int
    active_energy: float
    active_duration: float
    average_active_session_duration: float
    activity_distribution: Optional[Dict[str, ActivityDistribution]] = None
    peak_activity_time: Optional[PeakActivityTime] = None
    inactive_periods: Optional[List[InactivePeriod]] = None
    hourly_stats: Optional[List[HourlyStats]] = None

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
