from sqlalchemy.orm import declarative_base

Base = declarative_base()

# Import all models to ensure they are registered with the base
from .admin import Admin
from .care_intent import CareIntent
from .care_provider import CareProvider
from .health_facility import HealthFacility
from .package import Package
from .patient import Patient
from .patient_alcohol_consumption import PatientAlcoholConsumption
from .patient_connected_app import (
    PatientConnectedApp,
    PatientLibreView,
    PatientSinocare,
    PatientOtherApp,
)
from .patient_medication import PatientMedication
from .patient_daily_activity import PatientDailyActivity
from .patient_diabetic_history import PatientDiabeticHistory
from .patient_diet_plan import PatientDietPlan
from .patient_diet_preference import PatientDietPreference
from .patient_drug_allergy import PatientDrugAllergy
from .patient_eating_habit import PatientEatingHabit
from .patient_family_diabetic_history import PatientFamilyDiabeticHistory
from .patient_fitness_plan import PatientFitnessPlan
from .patient_food_allergy import PatientFoodAllergy
from .patient_meal import (
    PatientFoodItem,
    PatientMacroNutritionalValue,
    PatientMeal,
    PatientMicroNutritionalValue,
    PatientTotalMacroNutritionalValue,
    PatientTotalMicroNutritionalValue,
)
from .patient_meal_timing import PatientMealTiming
from .patient_medical_history import PatientMedicalHistory
from .patient_permission import PatientPermission
from .patient_prescription import PatientPrescription
from .patient_reproductive_health import PatientReproductiveHealth
from .patient_sleep_habit import PatientSleepHabit
from .patient_smbg import PatientSMBG
from .patient_smoking_habit import PatientSmokingHabit

from .token_usage_log import TokenUsageLog
from .user_device import UserDevice
from .patient_package_assignment import PatientPackageAssignment
from .weight_loss_agent import WeightLossAgentEnrollment
from .user_activity_log import UserActivityLog
from .patient_notification import PatientNotification
from .patient_report import PatientReport
from .patient_data_export import PatientDataExport
from .sleep_checkin import SleepCheckin
from .mood_entry import MoodEntry
from .symptom_entry import SymptomEntry, SymptomEntryItem
from .exercise import Exercise
from .patient_workout import PatientWorkout, PatientWorkoutSegment, PatientWorkoutExercise, PatientWorkoutSet
from .clinical_outcome import AdviceEvent, AdviceFollowup, ClinicalDecisionAudit
from .gamification import (
    Achievement,
    ActivityFeedEvent,
    Buddy,
    Challenge,
    ChallengeParticipant,
    Cheer,
    DailyTask,
    Group,
    GroupMember,
    LeaderboardEntry,
    PatientAchievement,
    PlayerProfile,
    WeeklyQuest,
    XPLedgerEntry,
)
