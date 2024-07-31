from datetime import datetime
from pydantic import BaseModel
from typing import Any, Dict, List, Optional, Union

from lib.schemas.meal import MealResponse


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


class GlucoseSummaryStats(BaseModel):
    average_glucose: float
    gmi: float
    gmi_mmol: float
    glucose_variability: float


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


class GlucoseLevelStats(BaseModel):
    from_date: datetime
    to_date: datetime
    glucose_readings: Optional[List[GlucoseReading]] = None
    meals: Optional[List[MealResponse]] = None
    glucose_summary_stats: GlucoseSummaryStats
    glucose_range_stats: GlucoseRangeStats
    hyper_stats: Optional[HyperStats]
    hypo_stats: Optional[HypoStats]
