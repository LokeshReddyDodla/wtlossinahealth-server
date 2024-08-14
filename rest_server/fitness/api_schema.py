from typing import List
from pydantic import BaseModel


class FitnessDataPoint(BaseModel):
    type: str
    source: str
    unit: str
    value: float
    dateFrom: str
    dateTo: str


class FitnessDataRequest(BaseModel):
    steps: List[FitnessDataPoint]
    active_energy_burned: List[FitnessDataPoint]
    blood_glucose: List[FitnessDataPoint]
    blood_pressure_diastolic: List[FitnessDataPoint]
    blood_pressure_systolic: List[FitnessDataPoint]
    heart_rate: List[FitnessDataPoint]
    sleep_in_bed: List[FitnessDataPoint]
