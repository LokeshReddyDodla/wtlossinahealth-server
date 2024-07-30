from datetime import datetime
from pydantic import BaseModel
from typing import Any, List, Optional


class CGMDataUpload(BaseModel):
    file: bytes
    patient_id: str
    device: str
    serial_number: str


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


class HyperStats(BaseModel):
    total_hyper_duration: float
    average_hyper_duration: float
    hyper_events_count: int
    hyper_events: List[HyperEvent]


class HypoStats(BaseModel):
    total_hypo_duration: float
    average_hypo_duration: float
    hypo_events_count: int
    hypo_events: List[HypoEvent]


class GlucoseLevelStats(BaseModel):
    glucose_readings: Optional[Any] = None
    glucose_summary_stats: GlucoseSummaryStats
    glucose_range_stats: GlucoseRangeStats
    hyper_stats: Optional[HyperStats]
    hypo_stats: Optional[HypoStats]
