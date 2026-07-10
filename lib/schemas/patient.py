from datetime import date, datetime
from typing import Any, List, Optional
from uuid import UUID

from pydantic import BaseModel

from lib.core.types import AiLanguageLiteral
from lib.schemas.care_provider import CareProvider
from lib.schemas.patient_alcohol_consumption import PatientAlcoholConsumption
from lib.schemas.patient_connected_app import PatientConnectedApp
from lib.schemas.patient_daily_activity import PatientDailyActivity
from lib.schemas.patient_diabetic_history import PatientDiabeticHistory
from lib.schemas.patient_diet_plan import PatientDietPlan
from lib.schemas.patient_drug_allergy import PatientDrugAllergy
from lib.schemas.patient_eating_habit import PatientEatingHabit
from lib.schemas.patient_family_diabetic_history import (
    PatientFamilyDiabeticHistory,
)
from lib.schemas.patient_fitness_plan import PatientFitnessPlan
from lib.schemas.patient_food_allergy import PatientFoodAllergy
from lib.schemas.patient_medical_history import PatientMedicalHistory
from lib.schemas.patient_package_assignment import (
    PatientPackageAssignment,
    PatientPackageAssignmentWithDetail,
)
from lib.schemas.patient_permission import PatientPermission
from lib.schemas.patient_reproductive_health import PatientReproductiveHealth
from lib.schemas.patient_sleep_habit import PatientSleepHabit
from lib.schemas.patient_smbg import PatientSMBG
from lib.schemas.patient_smoking_habit import PatientSmokingHabit

from lib.schemas.weight_loss_agent import WeightLossEnrollment


class PatientBase(BaseModel):
    first_name: Optional[str]
    last_name: Optional[str]
    dob: Optional[date]
    gender: Optional[str]
    profile_picture: Optional[str] = None
    height: Optional[float]
    waist: Optional[float]
    weight: Optional[float]
    height_cm: Optional[float] = None
    weight_kg: Optional[float] = None
    waist_cm: Optional[float] = None
    hip_cm: Optional[float] = None
    email: Optional[str]
    phone_number: str
    is_verified: Optional[bool] = False
    locale: Optional[str] = None
    timezone: Optional[str] = None
    occupation: Optional[str] = None
    preferred_ai_language: Optional[AiLanguageLiteral] = None


class PatientCreate(PatientBase):
    pass


class PatientUpdate(PatientBase):
    pass


class Patient(PatientBase):
    patient_id: UUID
    full_name: Optional[str]
    age: Optional[float]
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


class PatientDiabeticHistorySchema(Patient):
    diabetic_history: Optional[PatientDiabeticHistory] = None

    class Config:
        from_attributes = True


class CorePatientProfile(Patient):
    daily_activity: Optional[PatientDailyActivity] = None
    food_allergies: List[PatientFoodAllergy] = []
    drug_allergies: List[PatientDrugAllergy] = []
    alcohol_consumption: Optional[PatientAlcoholConsumption] = None
    smoking_habit: Optional[PatientSmokingHabit] = None
    eating_habit: Optional[PatientEatingHabit] = None
    sleep_habit: Optional[PatientSleepHabit] = None
    diabetic_history: Optional[PatientDiabeticHistory] = None
    reproductive_health: Optional[PatientReproductiveHealth] = None
    family_diabetic_histories: List[PatientFamilyDiabeticHistory] = []
    medical_histories: List[PatientMedicalHistory] = []
    diet_plans: List[PatientDietPlan] = []
    fitness_plans: List[PatientFitnessPlan] = []

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
    connected_apps: Optional[PatientConnectedApp] = None
    smbgs: List[PatientSMBG] = []
    # health_facility: Optional[HealthFacility] = None
    care_providers: List[CareProvider] = []
    package_assignments: List[PatientPackageAssignmentWithDetail] = []
    current_package: Optional[PatientPackageAssignmentWithDetail] = None
    weight_loss_enrollment: Optional[WeightLossEnrollment] = None

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
