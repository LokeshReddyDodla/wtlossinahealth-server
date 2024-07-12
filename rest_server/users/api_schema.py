from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import date

class UserBase(BaseModel):
    first_name: str
    last_name: str
    dob: date
    gender: str
    profile_picture: Optional[str] = None
    height: float
    waist: float
    weight: float
    email: str

class UserCreate(UserBase):
    pass

class UserUpdate(UserBase):
    pass

class DailyActivity(BaseModel):
    activity_level: str

class FoodAllergy(BaseModel):
    allergy_name: str

class MedicineAllergy(BaseModel):
    allergy_name: str

class DietPreference(BaseModel):
    preference: str

class AlcoholConsumption(BaseModel):
    consume_alcohol: bool
    frequency: Optional[str] = None
    quantity: Optional[str] = None
    type_of_alcohol: Optional[str] = None

class SmokingHabit(BaseModel):
    smoke_status: str
    years_of_smoking: Optional[int] = None
    cigarettes_per_day: Optional[int] = None
    quit_years_ago: Optional[int] = None

class MealTiming(BaseModel):
    timing: str

class CuisinePreference(BaseModel):
    cuisine: str

class SleepSummary(BaseModel):
    sleep_quality: str
    wake_up_fresh: bool
    drowsy_day: bool

class DiabeticHistory(BaseModel):
    type_of_diabetes: Optional[str] = None
    years_with_diabetes: Optional[int] = None
    is_pregnant: Optional[bool] = None
    pregnancy_weeks: Optional[int] = None

class FamilyDiabeticHistory(BaseModel):
    family_member: str

class MedicalHistory(BaseModel):
    condition: str
    duration_years: int
    details: Optional[str] = None

class CurrentMedication(BaseModel):
    has_medication: bool
    prescription_description: Optional[str] = None

class Prescription(BaseModel):
    prescription_file: str
