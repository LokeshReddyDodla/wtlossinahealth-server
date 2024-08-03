from pydantic import BaseModel
from typing import List, Optional
from datetime import date, datetime
from uuid import UUID

from lib.schemas.patient_permission import PatientPermission
from lib.schemas.patient_vitals import PatientVitals


class PatientBase(BaseModel):
    first_name: str
    last_name: str
    dob: date
    gender: str
    profile_picture: Optional[str] = None
    height: float
    waist: float
    weight: float
    email: str
    phone_number: str
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
    locale: Optional[str] = None


class PatientCreate(PatientBase):
    pass


class PatientUpdate(PatientBase):
    created_at: Optional[datetime]
    updated_at: Optional[datetime]


class Patient(PatientBase):
    patient_id: UUID

    class Config:
        orm_mode = True


class DailyActivityBase(BaseModel):
    activity_level: str


class DailyActivityCreate(DailyActivityBase):
    pass


class DailyActivity(DailyActivityBase):
    id: UUID
    patient_id: UUID

    class Config:
        orm_mode = True


class FoodAllergyBase(BaseModel):
    allergy_name: str


class FoodAllergyCreate(FoodAllergyBase):
    pass


class FoodAllergy(FoodAllergyBase):
    allergy_id: UUID
    patient_id: UUID

    class Config:
        orm_mode = True


class DrugAllergyBase(BaseModel):
    allergy_name: str


class DrugAllergyCreate(DrugAllergyBase):
    pass


class DrugAllergy(DrugAllergyBase):
    allergy_id: UUID
    patient_id: UUID

    class Config:
        orm_mode = True


class DietPreferenceBase(BaseModel):
    preference: str
    detail: Optional[str] = None


class DietPreferenceCreate(DietPreferenceBase):
    pass


class DietPreference(DietPreferenceBase):
    id: UUID
    patient_id: UUID

    class Config:
        orm_mode = True


class AlcoholConsumptionBase(BaseModel):
    consume_alcohol: bool
    frequency: Optional[str] = None
    quantity: Optional[str] = None
    type_of_alcohol: Optional[List[str]] = None


class AlcoholConsumptionCreate(AlcoholConsumptionBase):
    pass


class AlcoholConsumption(AlcoholConsumptionBase):
    id: UUID
    patient_id: UUID

    class Config:
        orm_mode = True


class SmokingHabitBase(BaseModel):
    smoke_status: str
    years_of_smoking: Optional[int] = None
    cigarettes_per_day: Optional[int] = None
    quit_years_ago: Optional[int] = None


class SmokingHabitCreate(SmokingHabitBase):
    pass


class SmokingHabit(SmokingHabitBase):
    id: UUID
    patient_id: UUID

    class Config:
        orm_mode = True


class MealTimingBase(BaseModel):
    meal_type: str
    time: str


class MealTimingCreate(MealTimingBase):
    pass


class MealTiming(MealTimingBase):
    id: UUID
    patient_id: UUID

    class Config:
        orm_mode = True


class CuisinePreferenceBase(BaseModel):
    cuisine: str


class CuisinePreferenceCreate(CuisinePreferenceBase):
    pass


class CuisinePreference(CuisinePreferenceBase):
    id: UUID
    patient_id: UUID

    class Config:
        orm_mode = True


class SleepSummaryBase(BaseModel):
    sleep_quality: str
    wake_up_fresh: bool
    drowsy_day: bool
    average_sleep_duration: Optional[float] = None
    wake_up_time: Optional[datetime] = None
    bed_time: Optional[datetime] = None


class SleepSummaryCreate(SleepSummaryBase):
    pass


class SleepSummary(SleepSummaryBase):
    patient_id: UUID

    class Config:
        orm_mode = True


class DiabeticHistoryBase(BaseModel):
    type_of_diabetes: Optional[str] = None
    years_with_diabetes: Optional[int] = None
    is_pregnant: Optional[bool] = None
    pregnancy_weeks: Optional[int] = None


class DiabeticHistoryCreate(DiabeticHistoryBase):
    pass


class DiabeticHistory(DiabeticHistoryBase):
    patient_id: UUID

    class Config:
        orm_mode = True


class FamilyDiabeticHistoryBase(BaseModel):
    family_member: str


class FamilyDiabeticHistoryCreate(FamilyDiabeticHistoryBase):
    pass


class FamilyDiabeticHistory(FamilyDiabeticHistoryBase):
    history_id: UUID
    patient_id: UUID

    class Config:
        orm_mode = True


class MedicalHistoryBase(BaseModel):
    condition: str
    duration_years: int
    details: Optional[str] = None


class MedicalHistoryCreate(MedicalHistoryBase):
    pass


class MedicalHistory(MedicalHistoryBase):
    history_id: UUID
    patient_id: UUID

    class Config:
        orm_mode = True


class CurrentMedicationBase(BaseModel):
    has_medication: bool
    prescription_description: Optional[str] = None
    prescription_image_url: Optional[str] = None


class CurrentMedicationCreate(CurrentMedicationBase):
    pass


class CurrentMedication(CurrentMedicationBase):
    medication_id: UUID
    patient_id: UUID

    class Config:
        orm_mode = True


class PrescriptionBase(BaseModel):
    prescription_file: str


class PrescriptionCreate(PrescriptionBase):
    pass


class Prescription(PrescriptionBase):
    prescription_id: UUID
    medication_id: UUID

    class Config:
        orm_mode = True


class PatientDetail(PatientBase):
    patient_id: UUID
    daily_activities: List[DailyActivity] = []
    food_allergies: List[FoodAllergy] = []
    drug_allergies: List[DrugAllergy] = []
    diet_preferences: List[DietPreference] = []
    alcohol_consumption: Optional[AlcoholConsumption] = None
    smoking_habits: Optional[SmokingHabit] = None
    meal_timings: List[MealTiming] = []
    cuisine_preferences: List[CuisinePreference] = []
    sleep_summary: Optional[SleepSummary] = None
    diabetic_history: Optional[DiabeticHistory] = None
    family_diabetic_history: List[FamilyDiabeticHistory] = []
    medical_history: List[MedicalHistory] = []
    current_medication: Optional[CurrentMedication] = None
    permissions: Optional[PatientPermission] = None
    vitals: List[PatientVitals] = []

    class Config:
        orm_mode = True
