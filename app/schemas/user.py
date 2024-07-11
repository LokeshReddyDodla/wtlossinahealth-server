from pydantic import BaseModel
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

class User(UserBase):
    user_id: int

    class Config:
        orm_mode = True

class DailyActivityBase(BaseModel):
    activity_level: str

class DailyActivityCreate(DailyActivityBase):
    pass

class DailyActivity(DailyActivityBase):
    id: int
    user_id: int

    class Config:
        orm_mode = True

class FoodAllergyBase(BaseModel):
    allergy_name: str

class FoodAllergyCreate(FoodAllergyBase):
    pass

class FoodAllergy(FoodAllergyBase):
    allergy_id: int
    user_id: int

    class Config:
        orm_mode = True

class MedicineAllergyBase(BaseModel):
    allergy_name: str

class MedicineAllergyCreate(MedicineAllergyBase):
    pass

class MedicineAllergy(MedicineAllergyBase):
    allergy_id: int
    user_id: int

    class Config:
        orm_mode = True

class DietPreferenceBase(BaseModel):
    preference: str

class DietPreferenceCreate(DietPreferenceBase):
    pass

class DietPreference(DietPreferenceBase):
    user_id: int

    class Config:
        orm_mode = True

class AlcoholConsumptionBase(BaseModel):
    consume_alcohol: bool
    frequency: Optional[str] = None
    quantity: Optional[str] = None
    type_of_alcohol: Optional[str] = None

class AlcoholConsumptionCreate(AlcoholConsumptionBase):
    pass

class AlcoholConsumption(AlcoholConsumptionBase):
    id: int
    user_id: int

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
    id: int
    user_id: int

    class Config:
        orm_mode = True

class MealTimingBase(BaseModel):
    timing: str

class MealTimingCreate(MealTimingBase):
    pass

class MealTiming(MealTimingBase):
    id: int
    user_id: int

    class Config:
        orm_mode = True

class CuisinePreferenceBase(BaseModel):
    cuisine: str

class CuisinePreferenceCreate(CuisinePreferenceBase):
    pass

class CuisinePreference(CuisinePreferenceBase):
    id: int
    user_id: int

    class Config:
        orm_mode = True

class SleepSummaryBase(BaseModel):
    sleep_quality: str
    wake_up_fresh: bool
    drowsy_day: bool

class SleepSummaryCreate(SleepSummaryBase):
    pass

class SleepSummary(SleepSummaryBase):
    user_id: int

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
    user_id: int

    class Config:
        orm_mode = True

class FamilyDiabeticHistoryBase(BaseModel):
    family_member: str

class FamilyDiabeticHistoryCreate(FamilyDiabeticHistoryBase):
    pass

class FamilyDiabeticHistory(FamilyDiabeticHistoryBase):
    history_id: int
    user_id: int

    class Config:
        orm_mode = True

class MedicalHistoryBase(BaseModel):
    condition: str
    duration_years: int
    details: Optional[str] = None

class MedicalHistoryCreate(MedicalHistoryBase):
    pass

class MedicalHistory(MedicalHistoryBase):
    history_id: int
    user_id: int

    class Config:
        orm_mode = True

class CurrentMedicationBase(BaseModel):
    has_medication: bool
    prescription_description: Optional[str] = None

class CurrentMedicationCreate(CurrentMedicationBase):
    pass

class CurrentMedication(CurrentMedicationBase):
    medication_id: int
    user_id: int

    class Config:
        orm_mode = True

class PrescriptionBase(BaseModel):
    prescription_file: str

class PrescriptionCreate(PrescriptionBase):
    pass

class Prescription(PrescriptionBase):
    prescription_id: int
    medication_id: int

    class Config:
        orm_mode = True
