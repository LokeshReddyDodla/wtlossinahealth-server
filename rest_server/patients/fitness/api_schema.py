from datetime import datetime
from typing import List

from pydantic import BaseModel

# TODO: pull vitals data from this fitness sync as well


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
    # Fitness
    steps: List[FitnessDataPoint] = []
    active_energy_burned: List[FitnessDataPoint] = []
    distance_walking_running: List[FitnessDataPoint] = []
    flights_climbed: List[FitnessDataPoint] = []
    exercise_time: List[FitnessDataPoint] = []
    workouts: List[FitnessDataPoint] = []
    # Blood glucose
    blood_glucose: List[FitnessDataPoint] = []
    # Vitals
    blood_pressure_diastolic: List[FitnessDataPoint] = []
    blood_pressure_systolic: List[FitnessDataPoint] = []
    heart_rate: List[FitnessDataPoint] = []
    blood_oxygen: List[FitnessDataPoint] = []
    resting_heart_rate: List[FitnessDataPoint] = []
    body_temperature: List[FitnessDataPoint] = []
    weight: List[FitnessDataPoint] = []
    respiratory_rate: List[FitnessDataPoint] = []
    # Sleep
    sleep_in_bed: List[FitnessDataPoint] = []
    sleep_deep: List[FitnessDataPoint] = []
    sleep_light: List[FitnessDataPoint] = []
    sleep_rem: List[FitnessDataPoint] = []
    sleep_awake: List[FitnessDataPoint] = []
    
