from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel

from rest_server.response_models import SuccessResponse


class FitnessDataPoint(BaseModel):
    type: str
    sourceName: str
    sourcePlatform: str
    unit: str
    value: float
    dateFrom: str
    dateTo: str


class FitnessDataRequest(BaseModel):
    dateFrom: datetime
    dateTo: datetime
    steps: List[FitnessDataPoint]
    active_energy_burned: List[FitnessDataPoint]
    blood_glucose: List[FitnessDataPoint]
    blood_pressure_diastolic: List[FitnessDataPoint]
    blood_pressure_systolic: List[FitnessDataPoint]
    heart_rate: List[FitnessDataPoint]
    sleep_in_bed: List[FitnessDataPoint]
    sleep_deep: List[FitnessDataPoint]
