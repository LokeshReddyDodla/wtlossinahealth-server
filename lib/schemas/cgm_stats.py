from datetime import date, datetime
from datetime import time as datetime_time
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel

from lib.schemas.fitness_stats import FitnessStats
from lib.schemas.patient_meal import PatientMeal


class CGMRangeStats(BaseModel):
    below_54: float
    below_70_above_54: float
    in_target_70_180: float
    above_180_below_250: float
    above_250: float


class CGMEvent(BaseModel):
    start_time: datetime
    end_time: datetime
    duration_minutes: float


class HyperEvent(CGMEvent):
    peak_glucose: float


class HypoEvent(CGMEvent):
    lowest_glucose: float


class AGPPoint(BaseModel):
    hour: str
    median: float
    percentile_10: float
    percentile_25: float
    percentile_75: float
    percentile_90: float


class CGMSummaryStats(BaseModel):
    average_glucose: float
    gmi: float
    gmi_mmol: float
    glucose_variability: float
    coefficient_of_variation: float
    standard_deviation: float
    highest_glucose: float
    highest_glucose_date: datetime
    lowest_glucose: float
    lowest_glucose_date: datetime
    agp_points: Optional[List[AGPPoint]] = None


class RapidSpikeEvent(BaseModel):
    start_time: datetime
    end_time: datetime
    initial_glucose: float
    peak_glucose: float
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
    initial_glucose: float
    lowest_glucose: float
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


class CGMReading(BaseModel):
    device_timestamp: Union[datetime, str]
    glucose: float


class CGMTimePeriodStats(BaseModel):
    average_glucose: float
    highest_glucose: float
    lowest_glucose: float
    out_of_range_percentage: float
    from_time: str
    to_time: str


class CGMStats(BaseModel):
    start_date: datetime
    end_date: datetime
    report_type: str

    cgm_readings: Optional[List[CGMReading]] = None
    cgm_summary_stats: CGMSummaryStats
    cgm_range_stats: CGMRangeStats
    hyper_stats: Optional[HyperStats]
    hypo_stats: Optional[HypoStats]
    time_period_stats: Optional[Dict[str, CGMTimePeriodStats]]

    fitness_report: Optional[FitnessStats] = None
    meal_report_id: Optional[str] = None
