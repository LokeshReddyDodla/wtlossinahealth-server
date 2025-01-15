from datetime import date, datetime
from datetime import time as datetime_time
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel

from lib.schemas.fitness_stats import FitnessStats
from lib.schemas.patient_meal import PatientMeal


class GlucoseRangeStats(BaseModel):
    below_54: float
    below_70_above_54: float
    in_target_70_180: float
    above_180_below_250: float
    above_250: float


class GlucoseEvent(BaseModel):
    start_time: datetime
    end_time: datetime
    duration: float


class HyperEvent(GlucoseEvent):
    peak_glucose_level: float


class HypoEvent(GlucoseEvent):
    lowest_glucose_level: float


class AGPPoint(BaseModel):
    hour: str
    median: float
    tenth_percentile: float
    ninetieth_percentile: float
    twenty_fifth_percentile: float
    seventy_fifth_percentile: float


class GlucoseSummaryStats(BaseModel):
    average_glucose: float
    gmi: float
    gmi_mmol: float
    glucose_variability: float
    glycemic_estimate: float
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
    initial_glucose_level: float
    peak_glucose_level: float
    duration: float


class RapidSpikeStats(BaseModel):
    total_spike_duration: float
    average_spike_duration: float
    spike_events_count: int
    spike_events: List[RapidSpikeEvent]


class RapidDropEvent(BaseModel):
    start_time: datetime
    end_time: datetime
    initial_glucose_level: float
    lowest_glucose_level: float
    duration: float


class RapidDropStats(BaseModel):
    total_drop_duration: float
    average_drop_duration: float
    drop_events_count: int
    drop_events: List[RapidDropEvent]


class HyperStats(BaseModel):
    total_hyper_duration: float
    average_hyper_duration: float
    hyper_events_count: int
    hyper_events: List[HyperEvent]
    rapid_spike_stats: RapidSpikeStats


class HypoStats(BaseModel):
    total_hypo_duration: float
    average_hypo_duration: float
    hypo_events_count: int
    hypo_events: List[HypoEvent]
    rapid_drop_stats: RapidDropStats


class GlucoseReading(BaseModel):
    Device_Timestamp: Union[datetime, str]
    Glucose_Level: float


class TimePeriodStats(BaseModel):
    average_glucose: float
    highest_glucose: float
    lowest_glucose: float
    out_of_range_percentage: float
    from_time: str
    to_time: str


class GlucoseLevelStats(BaseModel):
    start_date: datetime
    end_date: datetime
    glucose_readings: Optional[List[GlucoseReading]] = None
    meals: Optional[List[PatientMeal]] = None
    glucose_summary_stats: GlucoseSummaryStats
    glucose_range_stats: GlucoseRangeStats
    hyper_stats: Optional[HyperStats]
    hypo_stats: Optional[HypoStats]
    time_period_stats: Optional[Dict[str, TimePeriodStats]]
    fitness_report: Optional[FitnessStats] = None
