from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

# Import all models to ensure they are registered with the base
from .admin import Admin
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
from .patient_current_medication import PatientCurrentMedication
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
from .patient_prescription import PatientPrescriptionMedicine
from .patient_sleep import PatientSleep
from .patient_sleep_habit import PatientSleepHabit
from .patient_smbg import PatientSMBG
from .patient_smoking_habit import PatientSmokingHabit
from .patient_vital import PatientVital
from .token_usage_log import TokenUsageLog
from .user_device import UserDevice
from .patient_package_assignment import PatientPackageAssignment
from .weight_loss_agent import WeightLossAgentEnrollment
from .user_activity_log import UserActivityLog
from .patient_report import PatientReport
