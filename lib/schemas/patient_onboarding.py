"""Bundled patient onboarding request.

Single nested body posted from the onboarding flow on the device. Replaces the
old three-call sequence (basic / lifestyle / medical_history) with one atomic
transaction.

This is the FULL clean structure — all enums locked, list-of-objects shapes,
units in field names, reproductive_health as its own section, allergies with
severity/reaction, medical history with status/started_at.

The service layer dual-writes to legacy columns during the soak window
(see docs/onboarding-deploy2-codediff.md for the eventual cleanup).
"""
from datetime import date
from datetime import time as datetime_time
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from lib.core.types import AiLanguageLiteral


# ─────────────────────────── Enums (Literal types) ───────────────────────────

GenderEnum = Literal["MALE", "FEMALE", "OTHER", "PREFER_NOT_TO_SAY"]

ActivityLevelEnum = Literal[
    "SEDENTARY", "LIGHT", "MODERATE", "ACTIVE", "VERY_ACTIVE"
]

SleepQualityEnum = Literal["POOR", "FAIR", "AVERAGE", "GOOD", "EXCELLENT"]

SmokingStatusEnum = Literal["NEVER", "CURRENT", "FORMER"]
SmokeTypeEnum = Literal["CIGARETTES", "CIGARS", "VAPE", "HOOKAH", "OTHER"]

AlcoholStatusEnum = Literal["NEVER", "OCCASIONAL", "REGULAR", "FORMER"]
AlcoholFrequencyEnum = Literal["DAILY", "WEEKLY", "MONTHLY", "RARELY", "NEVER"]
AlcoholTypeEnum = Literal["BEER", "WINE", "SPIRITS", "COCKTAILS", "OTHER"]

DietPreferenceEnum = Literal[
    "VEG", "NON_VEG", "VEGAN", "EGGETARIAN", "JAIN",
    "KETO", "LOW_CARB", "DIABETIC_FRIENDLY", "HALAL", "KOSHER",
]

MealTypeEnum = Literal[
    "BREAKFAST", "LUNCH", "DINNER", "SNACK_AM", "SNACK_PM"
]

DiabetesTypeEnum = Literal[
    "NONE", "PRE", "T1", "T2", "GESTATIONAL", "LADA", "MODY", "OTHER"
]
FamilyDiabetesTypeEnum = Literal[
    "T1", "T2", "GESTATIONAL", "OTHER", "UNKNOWN"
]

FamilyMemberEnum = Literal[
    "FATHER", "MOTHER", "BROTHER", "SISTER", "SON", "DAUGHTER",
    "GRANDFATHER_PATERNAL", "GRANDMOTHER_PATERNAL",
    "GRANDFATHER_MATERNAL", "GRANDMOTHER_MATERNAL",
    "UNCLE", "AUNT",
]

MedicalConditionEnum = Literal[
    "HYPERTENSION", "HYPOTHYROIDISM", "HYPERTHYROIDISM", "PCOS",
    "KIDNEY_DISEASE", "LIVER_DISEASE", "HEART_DISEASE", "LUNG_DISEASE",
    "STROKE", "CANCER", "ASTHMA", "DEPRESSION", "ANXIETY",
    "SLEEP_APNEA", "OTHER",
]
MedicalStatusEnum = Literal["ACTIVE", "RESOLVED", "CHRONIC"]

FoodAllergyEnum = Literal[
    "DAIRY", "SHELLFISH", "NUTS", "TREE_NUTS", "PEANUTS",
    "EGGS", "GLUTEN", "SOY", "FISH", "OTHER",
]
DrugAllergyEnum = Literal[
    "PENICILLIN", "NSAIDS", "SULFA", "ASPIRIN", "OPIOIDS", "OTHER"
]
AllergySeverityEnum = Literal["MILD", "MODERATE", "SEVERE"]

MenopauseStatusEnum = Literal["PRE", "PERI", "POST", "NOT_APPLICABLE"]
PeriodRegularityEnum = Literal["REGULAR", "IRREGULAR", "NOT_APPLICABLE"]


# ─────────────────────────── Section schemas ─────────────────────────────────

class DailyActivityIn(BaseModel):
    activity_level: ActivityLevelEnum


class MealTimingIn(BaseModel):
    meal_type: MealTypeEnum
    time: datetime_time


class EatingHabitIn(BaseModel):
    meals_per_day: Optional[int] = Field(default=None, ge=0, le=10)
    snacks_count: Optional[int] = Field(default=None, ge=0, le=10)
    diet_preferences: List[DietPreferenceEnum] = []
    diet_preferences_detail: Optional[str] = None
    cuisine_preferences: List[str] = []
    meal_timings: List[MealTimingIn] = []


class FoodAllergyIn(BaseModel):
    name: FoodAllergyEnum
    name_other: Optional[str] = None
    severity: Optional[AllergySeverityEnum] = None


class DrugAllergyIn(BaseModel):
    name: DrugAllergyEnum
    name_other: Optional[str] = None
    reaction: Optional[str] = None


class DiabeticHistoryIn(BaseModel):
    type_of_diabetes: DiabetesTypeEnum = "NONE"
    years_with_diabetes: Optional[float] = Field(default=None, ge=0)
    diagnosed_at: Optional[date] = None


class FamilyDiabeticHistoryIn(BaseModel):
    family_member: FamilyMemberEnum
    type_of_diabetes: Optional[FamilyDiabetesTypeEnum] = None
    years_with_diabetes: Optional[float] = Field(default=None, ge=0)


class MedicalHistoryIn(BaseModel):
    condition: MedicalConditionEnum
    condition_other: Optional[str] = None
    status: Optional[MedicalStatusEnum] = None
    duration_years: float = Field(ge=0)
    started_at: Optional[date] = None
    details: Optional[str] = None


class AlcoholConsumptionIn(BaseModel):
    status: AlcoholStatusEnum
    frequency: Optional[AlcoholFrequencyEnum] = None
    drinks_per_session: Optional[int] = Field(default=None, ge=0)
    type_of_alcohol: List[AlcoholTypeEnum] = []
    quit_years_ago: Optional[int] = Field(default=None, ge=0)


class SmokingHabitIn(BaseModel):
    status: SmokingStatusEnum
    smoke_type: List[SmokeTypeEnum] = []
    cigarettes_per_day: Optional[int] = Field(default=None, ge=0)
    years_of_smoking: Optional[float] = Field(default=None, ge=0)
    quit_years_ago: Optional[int] = Field(default=None, ge=0)


class SleepHabitIn(BaseModel):
    sleep_quality: SleepQualityEnum
    average_sleep_hours: Optional[float] = Field(default=None, ge=0, le=24)
    bed_time: Optional[datetime_time] = None
    wake_up_time: Optional[datetime_time] = None
    wake_up_fresh: Optional[bool] = None
    drowsy_day: Optional[bool] = None
    snores: Optional[bool] = None


class ReproductiveHealthIn(BaseModel):
    is_pregnant: Optional[bool] = None
    pregnancy_weeks: Optional[int] = Field(default=None, ge=0, le=45)
    menopause_status: Optional[MenopauseStatusEnum] = None
    period_regularity: Optional[PeriodRegularityEnum] = None
    uses_contraception: Optional[bool] = None


# ─────────────────────────── Top-level request ───────────────────────────────

class PatientOnboardingRequest(BaseModel):
    # Identity
    first_name: str
    last_name: Optional[str] = None
    email: Optional[str] = None
    phone_number: Optional[str] = None
    gender: GenderEnum
    dob: date
    profile_picture: Optional[str] = None
    timezone: str  # IANA, e.g. "Asia/Kolkata"
    occupation: Optional[str] = None

    # Body (units in field names)
    height_cm: float = Field(ge=30, le=300)
    weight_kg: float = Field(ge=2, le=500)
    waist_cm: Optional[float] = Field(default=None, ge=20, le=300)
    hip_cm: Optional[float] = Field(default=None, ge=20, le=300)

    # Lifestyle
    daily_activity: DailyActivityIn
    eating_habit: EatingHabitIn
    alcohol_consumption: AlcoholConsumptionIn
    smoking_habit: SmokingHabitIn
    sleep_habit: SleepHabitIn
    food_allergies: List[FoodAllergyIn] = []

    # Medical
    diabetic_history: DiabeticHistoryIn
    drug_allergies: List[DrugAllergyIn] = []
    family_diabetic_histories: List[FamilyDiabeticHistoryIn] = []
    medical_histories: List[MedicalHistoryIn] = []

    # Reproductive (omit when gender != FEMALE)
    reproductive_health: Optional[ReproductiveHealthIn] = None


# ─────────────── Partial section schemas (for PATCH /v1/patients/profile) ───

class DailyActivityPartial(BaseModel):
    activity_level: Optional[ActivityLevelEnum] = None


class EatingHabitPartial(BaseModel):
    meals_per_day: Optional[int] = Field(default=None, ge=0, le=10)
    snacks_count: Optional[int] = Field(default=None, ge=0, le=10)
    diet_preferences: Optional[List[DietPreferenceEnum]] = None
    diet_preferences_detail: Optional[str] = None
    cuisine_preferences: Optional[List[str]] = None
    meal_timings: Optional[List[MealTimingIn]] = None


class AlcoholConsumptionPartial(BaseModel):
    status: Optional[AlcoholStatusEnum] = None
    frequency: Optional[AlcoholFrequencyEnum] = None
    drinks_per_session: Optional[int] = Field(default=None, ge=0)
    type_of_alcohol: Optional[List[AlcoholTypeEnum]] = None
    quit_years_ago: Optional[int] = Field(default=None, ge=0)


class SmokingHabitPartial(BaseModel):
    status: Optional[SmokingStatusEnum] = None
    smoke_type: Optional[List[SmokeTypeEnum]] = None
    cigarettes_per_day: Optional[int] = Field(default=None, ge=0)
    years_of_smoking: Optional[float] = Field(default=None, ge=0)
    quit_years_ago: Optional[int] = Field(default=None, ge=0)


class SleepHabitPartial(BaseModel):
    sleep_quality: Optional[SleepQualityEnum] = None
    average_sleep_hours: Optional[float] = Field(default=None, ge=0, le=24)
    bed_time: Optional[datetime_time] = None
    wake_up_time: Optional[datetime_time] = None
    wake_up_fresh: Optional[bool] = None
    drowsy_day: Optional[bool] = None
    snores: Optional[bool] = None


class DiabeticHistoryPartial(BaseModel):
    type_of_diabetes: Optional[DiabetesTypeEnum] = None
    years_with_diabetes: Optional[float] = Field(default=None, ge=0)
    diagnosed_at: Optional[date] = None


class ReproductiveHealthPartial(BaseModel):
    is_pregnant: Optional[bool] = None
    pregnancy_weeks: Optional[int] = Field(default=None, ge=0, le=45)
    menopause_status: Optional[MenopauseStatusEnum] = None
    period_regularity: Optional[PeriodRegularityEnum] = None
    uses_contraception: Optional[bool] = None


class PatientProfileUpdate(BaseModel):
    """Partial update — every field Optional. Sent fields overwrite,
    absent fields preserve, top-level lists replace whole."""

    # Identity
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    phone_number: Optional[str] = None
    gender: Optional[GenderEnum] = None
    dob: Optional[date] = None
    profile_picture: Optional[str] = None
    timezone: Optional[str] = None
    occupation: Optional[str] = None
    preferred_ai_language: Optional[AiLanguageLiteral] = None

    # Body
    height_cm: Optional[float] = Field(default=None, ge=30, le=300)
    weight_kg: Optional[float] = Field(default=None, ge=2, le=500)
    waist_cm: Optional[float] = Field(default=None, ge=20, le=300)
    hip_cm: Optional[float] = Field(default=None, ge=20, le=300)

    # Sections (partial-merge by inner fields)
    daily_activity: Optional[DailyActivityPartial] = None
    eating_habit: Optional[EatingHabitPartial] = None
    alcohol_consumption: Optional[AlcoholConsumptionPartial] = None
    smoking_habit: Optional[SmokingHabitPartial] = None
    sleep_habit: Optional[SleepHabitPartial] = None
    diabetic_history: Optional[DiabeticHistoryPartial] = None
    reproductive_health: Optional[ReproductiveHealthPartial] = None

    # Lists (replace whole when present)
    food_allergies: Optional[List[FoodAllergyIn]] = None
    drug_allergies: Optional[List[DrugAllergyIn]] = None
    family_diabetic_histories: Optional[List[FamilyDiabeticHistoryIn]] = None
    medical_histories: Optional[List[MedicalHistoryIn]] = None
