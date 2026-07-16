"""Pydantic models for whole-person holistic analysis in the weightloss agent.

Two families live here:
- Snapshot models: typed aggregation of one patient-local day of raw data
  (meals, fitness, glucose, medications, habits, InBody baseline).
- LLM output models: structured results returned by ModelGateway.extract —
  DailyCoachAnalysis, EveningReview and WholePersonSummary.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

AdherenceLevel = Literal["poor", "fair", "good", "excellent", "no_data"]
GlucoseControl = Literal["good", "fair", "poor", "no_data"]
ProteinAdequacy = Literal["low", "adequate", "high", "no_data"]
AnalysisStatus = Literal["pending", "complete", "failed_retrying"]


# ---------------------------------------------------------------------------
# Daily snapshot (aggregation output — LLM input)
# ---------------------------------------------------------------------------


class MealSnapshot(BaseModel):
    meal_id: str
    name: Optional[str] = None
    type: Optional[str] = None
    slot: Optional[str] = None
    time: Optional[str] = None
    calories: Optional[float] = None
    proteins: Optional[float] = None
    carbohydrates: Optional[float] = None
    simple_carbs: Optional[float] = None
    complex_carbs: Optional[float] = None
    fats: Optional[float] = None
    fiber: Optional[float] = None
    ai_insight: Optional[str] = None


class MealsDaily(BaseModel):
    meals_count: int = 0
    total_calories: Optional[float] = None
    total_proteins: Optional[float] = None
    total_carbohydrates: Optional[float] = None
    total_simple_carbs: Optional[float] = None
    total_complex_carbs: Optional[float] = None
    total_fats: Optional[float] = None
    total_fiber: Optional[float] = None
    meals: List[MealSnapshot] = Field(default_factory=list)


class WorkoutSnapshot(BaseModel):
    duration_minutes: Optional[int] = None
    calories_burned: Optional[float] = None
    exercises: List[str] = Field(default_factory=list)


class FitnessDaily(BaseModel):
    steps: Optional[int] = None
    active_energy_kcal: Optional[float] = None
    active_duration_min: Optional[int] = None
    workouts: List[WorkoutSnapshot] = Field(default_factory=list)


class GlucoseDaily(BaseModel):
    source: Optional[Literal["cgm", "smbg"]] = None
    readings_count: int = 0
    average_mgdl: Optional[float] = None
    min_mgdl: Optional[float] = None
    max_mgdl: Optional[float] = None
    time_in_range_percent: Optional[float] = None
    spikes_above_180: int = 0
    lows_below_70: int = 0


class Glp1Snapshot(BaseModel):
    injection_date: Optional[str] = None
    injection_frequency_days: Optional[int] = None
    days_since_last_injection: Optional[int] = None
    days_until_next_injection: Optional[int] = None


class MedicationSnapshot(BaseModel):
    name: str
    strength: Optional[str] = None
    purpose: Optional[str] = None
    food_timing: Optional[str] = None
    doses: List[Any] = Field(default_factory=list)
    schedule: Optional[Any] = None


class MedicationsSnapshot(BaseModel):
    active_medications: List[MedicationSnapshot] = Field(default_factory=list)
    glp1: Optional[Glp1Snapshot] = None


class HabitsSnapshot(BaseModel):
    meals_per_day: Optional[int] = None
    snacks_count: Optional[int] = None
    dietary_preferences: List[str] = Field(default_factory=list)
    cuisine_preferences: List[str] = Field(default_factory=list)
    average_sleep_hours: Optional[float] = None
    sleep_quality: Optional[str] = None
    smokes: Optional[bool] = None
    consumes_alcohol: Optional[bool] = None
    alcohol_frequency: Optional[str] = None
    activity_level: Optional[str] = None


class InbodyBaseline(BaseModel):
    report_id: Optional[str] = None
    report_date: Optional[str] = None
    inbody_score: Optional[Any] = None
    bmr_kcal: Optional[float] = None
    body_fat_percent: Optional[float] = None
    skeletal_muscle_mass_kg: Optional[float] = None
    visceral_fat_level: Optional[float] = None
    abnormal_indicators: List[str] = Field(default_factory=list)


class PatientContext(BaseModel):
    patient_id: str
    first_name: Optional[str] = None
    age: Optional[int] = None
    gender: Optional[str] = None
    height_cm: Optional[float] = None
    timezone: str = "Asia/Kolkata"
    current_weight_kg: Optional[float] = None
    target_weight_kg: Optional[float] = None
    target_bmi: Optional[float] = None
    program_goals: Optional[str] = None
    enrollment_date: Optional[str] = None


class HolisticDailySnapshot(BaseModel):
    patient_id: str
    date: str = Field(..., description="ISO date in the patient's local timezone")
    meals: Optional[MealsDaily] = None
    fitness: Optional[FitnessDaily] = None
    glucose: Optional[GlucoseDaily] = None
    medications: Optional[MedicationsSnapshot] = None
    habits: Optional[HabitsSnapshot] = None
    weight_kg: Optional[float] = None
    data_coverage: List[str] = Field(
        default_factory=list,
        description="Which blocks actually have data for this day",
    )


# ---------------------------------------------------------------------------
# LLM output models (ModelGateway.extract targets)
# ---------------------------------------------------------------------------


class DietVerdict(BaseModel):
    adherence: AdherenceLevel = "no_data"
    calories_consumed: Optional[float] = None
    calorie_target: Optional[float] = Field(
        None, description="Personalised target derived from BMR and goals"
    )
    protein_grams: Optional[float] = None
    protein_adequacy: ProteinAdequacy = "no_data"
    carb_quality_note: Optional[str] = None
    comments: str = ""


class ActivityVerdict(BaseModel):
    adherence: AdherenceLevel = "no_data"
    steps: Optional[int] = None
    steps_target: Optional[int] = None
    workout_done: Optional[bool] = None
    comments: str = ""


class GlucoseVerdict(BaseModel):
    control: GlucoseControl = "no_data"
    time_in_range_percent: Optional[float] = None
    spikes_noted: List[str] = Field(default_factory=list)
    comments: str = ""


class MedicationVerdict(BaseModel):
    on_track: Optional[bool] = None
    glp1_note: Optional[str] = None
    comments: str = ""


class DailyCoachAnalysis(BaseModel):
    """Structured verdict for one completed day, plus the coach message."""

    diet: DietVerdict
    activity: ActivityVerdict
    glucose: GlucoseVerdict
    medications: MedicationVerdict
    wins: List[str] = Field(default_factory=list, max_length=3)
    focus_for_tomorrow: List[str] = Field(default_factory=list, max_length=3)
    morning_message: str = Field(
        ...,
        description=(
            "Ready-to-send coach message for the next morning: what happened "
            "yesterday, whether it supports their progress, and what to do today. "
            "Warm, specific, references actual numbers, under 700 characters."
        ),
    )


class EveningReview(BaseModel):
    """Light end-of-day check-in generated from the same day's partial data."""

    completion_summary: str = Field(
        ..., description="One line on what was and wasn't completed today"
    )
    message: str = Field(
        ...,
        description=(
            "Ready-to-send evening message: acknowledge today's effort with real "
            "numbers and give one thing to carry into tomorrow. Under 500 characters."
        ),
    )


class WholePersonSummary(BaseModel):
    """The big-picture understanding of the patient, refreshed weekly or on new InBody."""

    body_status: str = Field(..., description="Body composition status from InBody")
    progress: str = Field(..., description="Weight trajectory vs enrollment targets")
    eating_pattern: str
    activity_pattern: str
    glucose_pattern: str
    medication_context: str
    habit_risks: List[str] = Field(default_factory=list)
    key_risks: List[str] = Field(default_factory=list)
    priorities: List[str] = Field(
        default_factory=list, description="Top 3 things to work on", max_length=3
    )
    overall_narrative: str = Field(
        ..., description="A short paragraph describing this person as a whole"
    )


# ---------------------------------------------------------------------------
# API response wrappers (stored-document shapes)
# ---------------------------------------------------------------------------


class DailyCoachAnalysisRecord(BaseModel):
    analysis_id: str
    patient_id: str
    enrollment_id: Optional[str] = None
    date: str
    status: AnalysisStatus
    attempts: int = 0
    snapshot: Optional[HolisticDailySnapshot] = None
    analysis: Optional[DailyCoachAnalysis] = None
    evening_review: Optional[EveningReview] = None
    error: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class WholePersonSummaryRecord(BaseModel):
    summary_id: str
    enrollment_id: str
    patient_id: str
    generated_at: Optional[str] = None
    days_analyzed: int = 0
    inbody_report_id: Optional[str] = None
    summary: Optional[WholePersonSummary] = None
    context: Dict[str, Any] = Field(default_factory=dict)
