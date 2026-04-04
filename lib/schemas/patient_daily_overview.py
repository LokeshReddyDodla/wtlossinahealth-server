from datetime import date
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


class GlucoseMetrics(BaseModel):
    average_glucose: float = 0.0
    time_in_range: float = 0.0


class FitnessMetrics(BaseModel):
    steps: int = 0
    active_energy: float = 0.0
    active_duration: int = 0


class SleepMetrics(BaseModel):
    duration: float = 0.0
    records_count: int = 0


class BloodPressure(BaseModel):
    systolic: Optional[float] = None
    diastolic: Optional[float] = None


class VitalsMetrics(BaseModel):
    blood_pressure: BloodPressure = BloodPressure()
    resting_heart_rate: Optional[float] = None


class PatientDailyOverviewResponse(BaseModel):
    date: date
    patient_id: str

    meals: MealDailySummary
    fitness: FitnessMetrics
    sleep: SleepMetrics
    glucose: GlucoseMetrics
    vitals: VitalsMetrics = VitalsMetrics()
    current_weight: Optional[float] = None
