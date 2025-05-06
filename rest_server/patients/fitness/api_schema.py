from datetime import datetime
from typing import List

from pydantic import BaseModel


class FitnessDataPoint(BaseModel):
    type: str
    source_name: str
    source_platform: str
    unit: str
    value: float
    start_datetime: str
    end_datetime: str


class FitnessDataRequest(BaseModel):
    start_datetime: datetime
    end_datetime: datetime
    steps: List[FitnessDataPoint]
    active_energy_burned: List[FitnessDataPoint]
    blood_glucose: List[FitnessDataPoint]
    blood_pressure_diastolic: List[FitnessDataPoint]
    blood_pressure_systolic: List[FitnessDataPoint]
    heart_rate: List[FitnessDataPoint]
    sleep_in_bed: List[FitnessDataPoint]
    sleep_deep: List[FitnessDataPoint]
    sleep_light: List[FitnessDataPoint]
    sleep_rem: List[FitnessDataPoint]
    sleep_awake: List[FitnessDataPoint]
    
