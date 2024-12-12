from datetime import date, datetime
from typing import Any, List, Optional
from uuid import UUID

from pydantic import BaseModel, HttpUrl
from sqlalchemy.orm import attributes

from lib.schemas.care_provider import CareProvider
from lib.schemas.health_facility import HealthFacility
from lib.schemas.package import Package
from lib.schemas.patient_alcohol_consumption import PatientAlcoholConsumption
from lib.schemas.patient_connected_app import PatientConnectedApp
from lib.schemas.patient_current_medication import PatientCurrentMedication
from lib.schemas.patient_daily_activity import PatientDailyActivity
from lib.schemas.patient_diabetic_history import PatientDiabeticHistory
from lib.schemas.patient_drug_allergy import PatientDrugAllergy
from lib.schemas.patient_eating_habit import PatientEatingHabit
from lib.schemas.patient_family_diabetic_history import \
    PatientFamilyDiabeticHistory
from lib.schemas.patient_food_allergy import PatientFoodAllergy
from lib.schemas.patient_medical_history import PatientMedicalHistory
from lib.schemas.patient_permission import PatientPermission
from lib.schemas.patient_plan import PatientPlan
from lib.schemas.patient_sleep_habit import PatientSleepHabit
from lib.schemas.patient_smbg import PatientSMBG
from lib.schemas.patient_smoking_habit import PatientSmokingHabit
from lib.schemas.patient_token_usage_log import PatientTokenUsageLog
from lib.schemas.patient_vital import PatientVital


class PatientBase(BaseModel):
    first_name: Optional[str]
    last_name: Optional[str]
    dob: Optional[date]
    gender: Optional[str]
    profile_picture: Optional[str] = None
    height: Optional[float]
    waist: Optional[float]
    weight: Optional[float]
    email: Optional[str]
    phone_number: str
    is_verified: Optional[bool] = False
    locale: Optional[str] = None


class PatientCreate(PatientBase):
    pass


class PatientUpdate(PatientBase):
    pass


class Patient(PatientBase):
    patient_id: UUID
    profile_completion: Optional[dict]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True

    @classmethod
    def from_orm(cls, obj):
        state = obj._sa_instance_state

        kwargs = {
            name: getattr(obj, name)
            for name in cls.model_fields
            if name in state.dict or name not in state.unloaded
        }

        return cls(**kwargs)


class CorePatientProfile(Patient):
    daily_activity: Optional[PatientDailyActivity] = None
    food_allergies: List[PatientFoodAllergy] = []
    drug_allergies: List[PatientDrugAllergy] = []
    alcohol_consumption: Optional[PatientAlcoholConsumption] = None
    smoking_habit: Optional[PatientSmokingHabit] = None
    eating_habit: Optional[PatientEatingHabit] = None
    sleep_habit: Optional[PatientSleepHabit] = None
    diabetic_history: Optional[PatientDiabeticHistory] = None
    family_diabetic_histories: List[PatientFamilyDiabeticHistory] = []
    medical_histories: List[PatientMedicalHistory] = []
    current_medication: Optional[PatientCurrentMedication] = None
    patient_plans: List[PatientPlan] = []

    class Config:
        from_attributes = True

    @classmethod
    def from_orm(cls, obj):
        state = obj._sa_instance_state

        kwargs = {
            name: getattr(obj, name)
            for name in cls.model_fields
            if name in state.dict or name not in state.unloaded
        }

        return cls(**kwargs)


class CompletePatientProfile(CorePatientProfile):
    permissions: Optional[PatientPermission] = None
    vitals: List[PatientVital] = []
    smbgs: List[PatientSMBG] = []
    connected_apps: Optional[PatientConnectedApp] = None
    token_usage_logs: List[PatientTokenUsageLog] = []
    health_facility: Optional[HealthFacility] = None
    care_providers: List[CareProvider] = []
    package: Optional[Package] = None

    class Config:
        from_attributes = True

    @classmethod
    def from_orm(cls, obj):
        state = obj._sa_instance_state

        kwargs = {
            name: getattr(obj, name)
            for name in cls.model_fields
            if name in state.dict or name not in state.unloaded
        }

        return cls(**kwargs)
