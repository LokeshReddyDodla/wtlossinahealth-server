from datetime import datetime
from typing import Dict, List, Optional, Union

from pydantic import BaseModel, Field

from lib.schemas.fitness_stats import FitnessStats


class DateRange(BaseModel):
    start: str = Field(..., description="Start date in ISO format")
    end: str = Field(..., description="End date in ISO format")


class ReportMetadata(BaseModel):
    date_range: DateRange
    total_readings: int = Field(..., description="Total number of CGM readings")
    days_covered: int = Field(..., description="Number of days covered in the report")
    report_type: str = Field(..., description="Type of report (daily, weekly, custom)")
    # % of expected 15-min sampling intervals that have data.
    sensor_active_percent: float = 0.0


class CGMRangeStats(BaseModel):
    below_54_percent: float
    below_70_above_54_percent: float
    in_target_70_180_percent: float
    above_180_below_250_percent: float
    above_250_percent: float
    # Tight range, additive to the canonical 70-180 TIR (not a replacement).
    in_tight_target_70_140_percent: float = 0.0
    # Pregnancy targets (63-140 range), 2019 consensus. None when the report has
    # not computed these bands — a missing value, distinct from a real 0%.
    in_target_63_140_percent: Optional[float] = None
    below_63_above_54_percent: Optional[float] = None
    above_140_percent: Optional[float] = None


class CGMEvent(BaseModel):
    start_time: datetime
    end_time: datetime
    duration_minutes: float


class HyperEvent(CGMEvent):
    peak_glucose_mgdl: float


class HypoEvent(CGMEvent):
    lowest_glucose_mgdl: float


class AGPPoint(BaseModel):
    hour: str
    median_mgdl: float
    percentile_10_mgdl: float
    percentile_25_mgdl: float
    percentile_75_mgdl: float
    percentile_90_mgdl: float


class CGMSummaryStats(BaseModel):
    average_glucose_mgdl: float
    gmi: float
    gmi_mmol: float
    # Glycemia Risk Index (Klonoff 2022), 0-100.
    gri: float = 0.0
    glucose_variability_percent: float
    coefficient_of_variation_percent: float
    std_dev_glucose_mgdl: float
    highest_glucose_mgdl: float
    highest_glucose_date: datetime
    lowest_glucose_mgdl: float
    lowest_glucose_date: datetime
    # % of overnight (00:00-05:59) readings below 70.
    nocturnal_time_below_70_percent: float = 0.0
    # Dawn phenomenon: avg(03:00-05:59) - avg(00:00-02:59), positive = pre-wake rise.
    dawn_rise_mgdl: float = 0.0
    agp_points: Optional[List[AGPPoint]] = None


class RapidSpikeEvent(BaseModel):
    start_time: datetime
    end_time: datetime
    initial_glucose_mgdl: float
    peak_glucose_mgdl: float
    peak_glucose_time: datetime
    duration_minutes: float


class RapidSpikeStats(BaseModel):
    total_spike_duration_minutes: float
    average_spike_duration_minutes: float
    spike_events_count: int
    spike_events: List[RapidSpikeEvent]


class RapidDropEvent(BaseModel):
    start_time: datetime
    end_time: datetime
    initial_glucose_mgdl: float
    lowest_glucose_mgdl: float
    lowest_glucose_time: datetime
    duration_minutes: float


class RapidDropStats(BaseModel):
    total_drop_duration_minutes: float
    average_drop_duration_minutes: float
    drop_events_count: int
    drop_events: List[RapidDropEvent]


class HyperStats(BaseModel):
    total_hyper_duration_minutes: float
    average_hyper_duration_minutes: float
    hyper_events_count: int
    hyper_events: List[HyperEvent]
    rapid_spike_stats: RapidSpikeStats


class HypoStats(BaseModel):
    total_hypo_duration_minutes: float
    average_hypo_duration_minutes: float
    hypo_events_count: int
    hypo_events: List[HypoEvent]
    rapid_drop_stats: RapidDropStats


class CGMTrend(BaseModel):
    """This period vs the immediately-preceding equal-length window."""

    previous_average_glucose_mgdl: float
    previous_time_in_range_percent: float
    delta_average_glucose_mgdl: float
    delta_time_in_range_percent: float
    delta_gmi: float


class CGMReading(BaseModel):
    device_timestamp: Union[datetime, str]
    glucose_mgdl: float


class CGMTimePeriodStats(BaseModel):
    average_glucose_mgdl: float
    highest_glucose_mgdl: float
    lowest_glucose_mgdl: float
    out_of_range_percent: float
    from_time: str
    to_time: str


class CGMStats(BaseModel):
    metadata: ReportMetadata
    cgm_readings: Optional[List[CGMReading]] = None
    cgm_summary_stats: CGMSummaryStats
    cgm_range_stats: CGMRangeStats
    hyper_stats: Optional[HyperStats]
    hypo_stats: Optional[HypoStats]
    time_period_stats: Optional[Dict[str, CGMTimePeriodStats]]
    trend: Optional[CGMTrend] = None

    fitness_report: Optional[FitnessStats] = None
    meal_report_id: Optional[str] = None

    @property
    def start_date(self):
        """Backward compatibility: return start date from metadata."""
        return datetime.fromisoformat(
            self.metadata.date_range.start.replace("Z", "+00:00")
        )

    @property
    def end_date(self):
        """Backward compatibility: return end date from metadata."""
        return datetime.fromisoformat(
            self.metadata.date_range.end.replace("Z", "+00:00")
        )

    @property
    def report_type(self):
        """Backward compatibility: return report type from metadata."""
        return self.metadata.report_type
