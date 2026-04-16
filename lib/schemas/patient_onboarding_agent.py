"""Schemas for the patient onboarding chat agent."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class OnboardingField(str, Enum):
    # Basic
    FIRST_NAME = "first_name"
    LAST_NAME = "last_name"
    EMAIL = "email"
    DOB = "dob"
    GENDER = "gender"
    HEIGHT = "height"
    WEIGHT = "weight"
    WAIST = "waist"
    LOCALE = "locale"

    # Lifestyle
    ACTIVITY_LEVEL = "activity_level"
    CONSUME_ALCOHOL = "consume_alcohol"
    ALCOHOL_FREQUENCY = "alcohol_frequency"
    ALCOHOL_QUANTITY = "alcohol_quantity"
    TYPE_OF_ALCOHOL = "type_of_alcohol"
    SMOKE_STATUS = "smoke_status"
    YEARS_OF_SMOKING = "years_of_smoking"
    CIGARETTES_PER_DAY = "cigarettes_per_day"
    QUIT_YEARS_AGO = "quit_years_ago"
    SLEEP_QUALITY = "sleep_quality"
    WAKE_UP_FRESH = "wake_up_fresh"
    DROWSY_DAY = "drowsy_day"
    AVERAGE_SLEEP_DURATION = "average_sleep_duration"
    WAKE_UP_TIME = "wake_up_time"
    BED_TIME = "bed_time"
    MEALS_PER_DAY = "meals_per_day"
    SNACKS_COUNT = "snacks_count"
    FOOD_ALLERGIES = "food_allergies"

    # Medical history
    TYPE_OF_DIABETES = "type_of_diabetes"
    YEARS_WITH_DIABETES = "years_with_diabetes"
    IS_PREGNANT = "is_pregnant"
    PREGNANCY_WEEKS = "pregnancy_weeks"
    HAS_MEDICATION = "has_medication"
    PRESCRIPTION_DESCRIPTION = "prescription_description"
    DRUG_ALLERGIES = "drug_allergies"
    MEDICAL_CONDITIONS = "medical_conditions"

    @classmethod
    def human_labels(cls) -> Dict[str, str]:
        return {
            cls.FIRST_NAME.value: "First Name",
            cls.LAST_NAME.value: "Last Name",
            cls.EMAIL.value: "Email",
            cls.DOB.value: "Date of Birth",
            cls.GENDER.value: "Gender",
            cls.HEIGHT.value: "Height (cm)",
            cls.WEIGHT.value: "Weight (kg)",
            cls.WAIST.value: "Waist (cm)",
            cls.LOCALE.value: "Locale / Language",
            cls.ACTIVITY_LEVEL.value: "Activity Level",
            cls.CONSUME_ALCOHOL.value: "Alcohol Consumption",
            cls.ALCOHOL_FREQUENCY.value: "Alcohol Frequency",
            cls.ALCOHOL_QUANTITY.value: "Alcohol Quantity",
            cls.TYPE_OF_ALCOHOL.value: "Types of Alcohol",
            cls.SMOKE_STATUS.value: "Smoking Status",
            cls.YEARS_OF_SMOKING.value: "Years of Smoking",
            cls.CIGARETTES_PER_DAY.value: "Cigarettes Per Day",
            cls.QUIT_YEARS_AGO.value: "Years Since Quitting Smoking",
            cls.SLEEP_QUALITY.value: "Sleep Quality",
            cls.WAKE_UP_FRESH.value: "Wake Up Fresh",
            cls.DROWSY_DAY.value: "Drowsy in the Day",
            cls.AVERAGE_SLEEP_DURATION.value: "Average Sleep Duration",
            cls.WAKE_UP_TIME.value: "Wake Up Time",
            cls.BED_TIME.value: "Bed Time",
            cls.MEALS_PER_DAY.value: "Meals Per Day",
            cls.SNACKS_COUNT.value: "Snacks Per Day",
            cls.FOOD_ALLERGIES.value: "Food Allergies",
            cls.TYPE_OF_DIABETES.value: "Type of Diabetes",
            cls.YEARS_WITH_DIABETES.value: "Years with Diabetes",
            cls.IS_PREGNANT.value: "Currently Pregnant",
            cls.PREGNANCY_WEEKS.value: "Pregnancy Weeks",
            cls.HAS_MEDICATION.value: "Currently on Medication",
            cls.PRESCRIPTION_DESCRIPTION.value: "Medication Description",
            cls.DRUG_ALLERGIES.value: "Drug Allergies",
            cls.MEDICAL_CONDITIONS.value: "Medical Conditions",
        }

    @classmethod
    def list_for_prompt(cls) -> str:
        labels = cls.human_labels()
        return "\n".join(
            f"- {field.value} ({labels[field.value]})" for field in cls
        )


FIELD_TO_SECTION: Dict[str, str] = {
    OnboardingField.FIRST_NAME.value: "basic",
    OnboardingField.LAST_NAME.value: "basic",
    OnboardingField.EMAIL.value: "basic",
    OnboardingField.DOB.value: "basic",
    OnboardingField.GENDER.value: "basic",
    OnboardingField.HEIGHT.value: "basic",
    OnboardingField.WEIGHT.value: "basic",
    OnboardingField.WAIST.value: "basic",
    OnboardingField.LOCALE.value: "basic",
    OnboardingField.ACTIVITY_LEVEL.value: "lifestyle",
    OnboardingField.CONSUME_ALCOHOL.value: "lifestyle",
    OnboardingField.ALCOHOL_FREQUENCY.value: "lifestyle",
    OnboardingField.ALCOHOL_QUANTITY.value: "lifestyle",
    OnboardingField.TYPE_OF_ALCOHOL.value: "lifestyle",
    OnboardingField.SMOKE_STATUS.value: "lifestyle",
    OnboardingField.YEARS_OF_SMOKING.value: "lifestyle",
    OnboardingField.CIGARETTES_PER_DAY.value: "lifestyle",
    OnboardingField.QUIT_YEARS_AGO.value: "lifestyle",
    OnboardingField.SLEEP_QUALITY.value: "lifestyle",
    OnboardingField.WAKE_UP_FRESH.value: "lifestyle",
    OnboardingField.DROWSY_DAY.value: "lifestyle",
    OnboardingField.AVERAGE_SLEEP_DURATION.value: "lifestyle",
    OnboardingField.WAKE_UP_TIME.value: "lifestyle",
    OnboardingField.BED_TIME.value: "lifestyle",
    OnboardingField.MEALS_PER_DAY.value: "lifestyle",
    OnboardingField.SNACKS_COUNT.value: "lifestyle",
    OnboardingField.FOOD_ALLERGIES.value: "lifestyle",
    OnboardingField.TYPE_OF_DIABETES.value: "medical_history",
    OnboardingField.YEARS_WITH_DIABETES.value: "medical_history",
    OnboardingField.IS_PREGNANT.value: "medical_history",
    OnboardingField.PREGNANCY_WEEKS.value: "medical_history",
    OnboardingField.HAS_MEDICATION.value: "medical_history",
    OnboardingField.PRESCRIPTION_DESCRIPTION.value: "medical_history",
    OnboardingField.DRUG_ALLERGIES.value: "medical_history",
    OnboardingField.MEDICAL_CONDITIONS.value: "medical_history",
}

REQUIRED_FIELDS: List[str] = [
    OnboardingField.FIRST_NAME.value,
    OnboardingField.LAST_NAME.value,
    OnboardingField.EMAIL.value,
    OnboardingField.DOB.value,
    OnboardingField.GENDER.value,
    OnboardingField.HEIGHT.value,
    OnboardingField.WEIGHT.value,
    OnboardingField.WAIST.value,
    OnboardingField.ACTIVITY_LEVEL.value,
    OnboardingField.CONSUME_ALCOHOL.value,
    OnboardingField.SMOKE_STATUS.value,
    OnboardingField.SLEEP_QUALITY.value,
    OnboardingField.MEALS_PER_DAY.value,
    OnboardingField.SNACKS_COUNT.value,
    OnboardingField.TYPE_OF_DIABETES.value,
    OnboardingField.HAS_MEDICATION.value,
]

QUESTION_ORDER: List[str] = list(REQUIRED_FIELDS)


class OnboardingState(str, Enum):
    COLLECTING = "collecting"
    REVIEWING = "reviewing"
    APPLYING = "applying"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


ActionType = Literal["set", "remove", "confirm_all", "cancel_all"]


class LLMAction(BaseModel):
    action: ActionType
    field: Optional[str] = None
    value: Optional[Any] = None


class LLMResponse(BaseModel):
    actions: List[LLMAction] = Field(default_factory=list)
    reply: str = ""


class PatientOnboardingChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)


class PatientOnboardingStartRequest(BaseModel):
    restart: bool = False


class PatientOnboardingChatResponse(BaseModel):
    reply: str
    state: str
    current_question_field: Optional[str] = None
    missing_required_fields: List[str] = Field(default_factory=list)
    draft_changes: Optional[Dict[str, Any]] = None
    applied_changes: Optional[Dict[str, Any]] = None


class OnboardingSessionSummaryResponse(BaseModel):
    state: str
    current_question_field: Optional[str] = None
    missing_required_fields: List[str] = Field(default_factory=list)
    draft_changes: Dict[str, Any] = Field(default_factory=dict)
    message_count: int = 0
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
