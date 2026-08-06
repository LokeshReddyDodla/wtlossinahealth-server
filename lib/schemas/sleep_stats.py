from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class SleepStageSpan(BaseModel):
    start: str = Field(..., description="Segment start (naive ISO datetime)")
    end: str = Field(..., description="Segment end (naive ISO datetime)")
    stage: str = Field(..., description="deep | light | rem | awake")


class DateRange(BaseModel):
    start: str = Field(..., description="Start date in ISO format")
    end: str = Field(..., description="End date in ISO format")


class ReportMetadata(BaseModel):
    date_range: DateRange = Field(..., description="Date range for the report")
    total_sessions: int = Field(..., description="Total number of sleep sessions")
    days_covered: int = Field(..., description="Number of days covered in the report")
    days_with_data: int = Field(0, description="Number of nights with sleep data")
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
    average_awakenings: Optional[float] = Field(
        None, description="Average awake episodes per night (fragmentation)"
    )
    average_waso_minutes: Optional[float] = Field(
        None, description="Average wake time within the sleep window per night (WASO)"
    )


class SleepConsistency(BaseModel):
    nights_tracked: int = Field(0, description="Nights with staged sleep data")
    bedtime_variability_minutes: Optional[float] = Field(
        None, description="Std deviation of bedtime across nights (lower = more regular)"
    )
    wake_variability_minutes: Optional[float] = Field(
        None, description="Std deviation of wake time across nights"
    )
    consistency_score: Optional[float] = Field(
        None, description="0-100 regularity score derived from timing variability (product score, not a validated instrument)"
    )
    average_nightly_sleep_minutes: Optional[float] = Field(
        None, description="Average asleep time per night (deep+light+rem)"
    )
    recommended_min_minutes: float = Field(
        420.0, description="Recommended minimum nightly sleep (AASM: >= 7h)"
    )
    sleep_debt_minutes: Optional[float] = Field(
        None, description="Average nightly shortfall below the recommended minimum"
    )
    wearable_nights: int = Field(0, description="Nights sourced from device data")
    manual_nights: int = Field(0, description="Nights sourced from manual check-ins")
    subjective_quality: Optional[float] = Field(
        None, description="Average self-rated quality (1-5) from manual check-ins"
    )


class SleepTrend(BaseModel):
    previous_average_sleep_minutes: Optional[float] = None
    delta_average_sleep_minutes: Optional[float] = None
    previous_consistency_score: Optional[float] = None
    delta_consistency_score: Optional[float] = None
    # Per-night stage + efficiency change vs the previous window.
    delta_deep_minutes: Optional[float] = None
    delta_rem_minutes: Optional[float] = None
    delta_light_minutes: Optional[float] = None
    delta_awake_minutes: Optional[float] = None
    delta_efficiency: Optional[float] = None


class SleepStats(BaseModel):
    metadata: ReportMetadata
    duration: SleepDuration
    type_distribution: SleepTypeDistribution
    timing: SleepTiming
    quality: SleepQuality
    consistency: Optional[SleepConsistency] = None
    trend: Optional[SleepTrend] = None
    hypnogram: Optional[List[SleepStageSpan]] = Field(
        None,
        description="Timed stage segments for a single night (daily reports only) "
        "— the depth-over-night shape the aggregate stats can't express",
    )
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
