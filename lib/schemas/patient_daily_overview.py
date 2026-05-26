from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel


class MacroNutrients(BaseModel):
    carbohydrates: float = 0.0
    proteins: float = 0.0
    fats: float = 0.0
    fiber: float = 0.0
    calories: float = 0.0


class MealDailySummary(BaseModel):
    daily: MacroNutrients
    diet_recommendations: Optional[dict] = None


class GlucoseReading(BaseModel):
    timestamp: datetime
    value: float


class GlucoseRange(BaseModel):
    below_54: float = 0.0
    below_70: float = 0.0
    in_target: float = 0.0
    above_180: float = 0.0
    above_250: float = 0.0


class GlucoseMetrics(BaseModel):
    average_glucose: float = 0.0
    time_in_range: float = 0.0
    range: GlucoseRange = GlucoseRange()
    readings: list[GlucoseReading] | None = None


class HourlySteps(BaseModel):
    hour: int
    steps: int


class FitnessMetrics(BaseModel):
    steps: int = 0
    active_energy: float = 0.0
    active_duration: int = 0
    hourly_steps: list[HourlySteps] | None = None


class SleepMetrics(BaseModel):
    duration: float = 0.0
    records_count: int = 0


class BloodPressure(BaseModel):
    systolic: Optional[float] = None
    diastolic: Optional[float] = None


class VitalReading(BaseModel):
    timestamp: datetime
    value: float


class VitalsMetrics(BaseModel):
    blood_pressure: BloodPressure = BloodPressure()
    resting_heart_rate: Optional[float] = None
    resting_heart_rate_trend: list[VitalReading] | None = None


class WorkoutMetrics(BaseModel):
    """Manually-logged workout sessions for the day.

    Distinct from FitnessMetrics (which comes from Apple Health / Health Connect
    sync and reports steps + active energy). This reports user-intent gym sessions."""
    session_count: int = 0
    total_duration_minutes: int = 0
    total_calories: float = 0.0
    types: list[str] = []


class PatientDailyOverviewResponse(BaseModel):
    date: date
    patient_id: str

    meals: MealDailySummary
    fitness: FitnessMetrics
    sleep: SleepMetrics
    glucose: GlucoseMetrics
    vitals: VitalsMetrics = VitalsMetrics()
    workouts: WorkoutMetrics = WorkoutMetrics()
    current_weight: Optional[float] = None
    weight_trend: list[VitalReading] | None = None
