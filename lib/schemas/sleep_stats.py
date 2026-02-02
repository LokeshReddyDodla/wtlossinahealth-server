from datetime import datetime
from typing import Dict, Optional

from pydantic import BaseModel, Field


class DateRange(BaseModel):
    start: str = Field(..., description="Start date in ISO format")
    end: str = Field(..., description="End date in ISO format")


class ReportMetadata(BaseModel):
    date_range: DateRange = Field(..., description="Date range for the report")
    total_sessions: int = Field(..., description="Total number of sleep sessions")
    days_covered: int = Field(..., description="Number of days covered in the report")
    report_type: str = Field(..., description="Type of report (daily, weekly, monthly, custom)")


class SleepDuration(BaseModel):
    total_duration: Optional[float] = Field(None, description="Total sleep duration in minutes")
    average_duration: Optional[float] = Field(None, description="Average sleep duration in minutes")
    per_day_average_duration: Optional[float] = Field(None, description="Per day average duration in minutes")
    longest_sleep: Optional[float] = Field(None, description="Longest sleep duration in minutes")
    shortest_sleep: Optional[float] = Field(None, description="Shortest sleep duration in minutes")


class SleepTypeDistribution(BaseModel):
    total_duration: float = Field(..., description="Total duration in minutes")
    per_day_average_total: float = Field(..., description="Per day average total in minutes")
    distribution: Dict[str, Dict[str, float]] = Field(..., description="Distribution by sleep type")


class SleepTiming(BaseModel):
    earliest_start_time: Optional[str] = Field(None, description="Earliest sleep start time (ISO format)")
    latest_end_time: Optional[str] = Field(None, description="Latest sleep end time (ISO format)")
    average_start_time: Optional[str] = Field(None, description="Average sleep start time (ISO format)")
    average_end_time: Optional[str] = Field(None, description="Average sleep end time (ISO format)")


class SleepQuality(BaseModel):
    deep_sleep_percentage: float = Field(..., description="Deep sleep percentage")
    rem_sleep_percentage: float = Field(..., description="REM sleep percentage")
    awake_time_percentage: float = Field(..., description="Awake time percentage")
    restorative_sleep: float = Field(..., description="Restorative sleep percentage")
    sleep_efficiency: float = Field(..., description="Sleep efficiency percentage")
    sleep_quality: str = Field(..., description="Sleep quality classification")


class SleepStats(BaseModel):
    metadata: ReportMetadata
    duration: SleepDuration
    type_distribution: SleepTypeDistribution
    timing: SleepTiming
    quality: SleepQuality
    feedback: Optional[str] = Field(None, description="AI-generated feedback")

    @property
    def start_date(self):
        """Backward compatibility: return start date from metadata."""
        return datetime.fromisoformat(self.metadata.date_range.start.replace("Z", "+00:00"))

    @property
    def end_date(self):
        """Backward compatibility: return end date from metadata."""
        return datetime.fromisoformat(self.metadata.date_range.end.replace("Z", "+00:00"))

    @property
    def report_type(self):
        """Backward compatibility: return report type from metadata."""
        return self.metadata.report_type
