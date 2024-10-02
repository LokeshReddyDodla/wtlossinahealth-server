from datetime import date, datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, HttpUrl
from sqlalchemy.orm import attributes

from lib.schemas.care_provider import CareProvider
from lib.schemas.health_facility import HealthFacility
from lib.schemas.patient_alcohol_consumption import PatientAlcoholConsumption
from lib.schemas.patient_care_provider import PatientCareProvider
from lib.schemas.patient_connected_app import PatientConnectedApp
from lib.schemas.patient_cuisine_preference import PatientCuisinePreference
from lib.schemas.patient_current_medication import PatientCurrentMedication
from lib.schemas.patient_daily_activity import PatientDailyActivity
from lib.schemas.patient_diabetic_history import PatientDiabeticHistory
from lib.schemas.patient_diet_preference import PatientDietPreference
from lib.schemas.patient_drug_allergy import PatientDrugAllergy
from lib.schemas.patient_family_diabetic_history import \
    PatientFamilyDiabeticHistory
from lib.schemas.patient_fitness_data_sync import PatientFitnessDataSync
from lib.schemas.patient_food_allergy import PatientFoodAllergy
from lib.schemas.patient_meal_timing import PatientMealTiming
from lib.schemas.patient_medical_history import PatientMedicalHistory
from lib.schemas.patient_permission import PatientPermission
from lib.schemas.patient_sleep_habit import PatientSleepHabit
from lib.schemas.patient_smbg import PatientSMBG
from lib.schemas.patient_smoking_habit import PatientSmokingHabit
from lib.schemas.patient_token_usage_log import PatientTokenUsageLog
from lib.schemas.patient_vital import PatientVital


class PatientBase(BaseModel):
    first_name: str
    last_name: str
    dob: date
    gender: str
    profile_picture: Optional[HttpUrl] = None
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


class CompletePatientProfile(PatientBase):    
    patient_id: UUID
    daily_activity: Optional[PatientDailyActivity] = None
    food_allergies: List[PatientFoodAllergy] = []
    drug_allergies: List[PatientDrugAllergy] = []
    diet_preferences: List[PatientDietPreference] = []
    alcohol_consumption: Optional[PatientAlcoholConsumption] = None
    smoking_habit: Optional[PatientSmokingHabit] = None
    meal_timings: List[PatientMealTiming] = []
    cuisine_preferences: List[PatientCuisinePreference] = []
    sleep_habit: Optional[PatientSleepHabit] = None
    diabetic_history: Optional[PatientDiabeticHistory] = None
    family_diabetic_histories: List[PatientFamilyDiabeticHistory] = []
    medical_histories: List[PatientMedicalHistory] = []
    current_medication: Optional[PatientCurrentMedication] = None
    permissions: Optional[PatientPermission] = None
    vitals: List[PatientVital] = []
    smbgs: List[PatientSMBG] = []
    connected_apps: Optional[PatientConnectedApp] = None
    fitness_sync: Optional[PatientFitnessDataSync] = None
    token_usage_logs: List[PatientTokenUsageLog] = []
    care_providers: List[PatientCareProvider] = []
    health_facility: Optional[HealthFacility] = None

    class Config:
        orm_mode = True

    @classmethod
    def from_orm(cls, obj):
        state = obj._sa_instance_state

        kwargs = {
            name: getattr(obj, name)
            for name in cls.__fields__
            if name in state.dict or name not in state.unloaded
        }

        return cls(**kwargs)

