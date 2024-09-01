from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

# Import all models to ensure they are registered with the base
from .admin import Admin
from .patient_alcohol_consumption import PatientAlcoholConsumption
from .patient_connected_app import (
    PatientConnectedApp,
    PatientLibreView,
    PatientOtherApp,
)
from .patient_cuisine_preference import PatientCuisinePreference
from .patient_current_medication import PatientCurrentMedication
from .patient_daily_activity import PatientDailyActivity
from .patient_diabetic_history import PatientDiabeticHistory
from .patient_diet_preference import PatientDietPreference
from .patient_drug_allergy import PatientDrugAllergy
from .patient_family_diabetic_history import PatientFamilyDiabeticHistory
from .patient_fitness_data_sync import PatientFitnessDataSync
from .patient_food_allergy import PatientFoodAllergy
from .patient_meal_timing import PatientMealTiming
from .patient_meal import (
    PatientMeal,
    PatientFoodItem,
    PatientMacroNutritionalValue,
    PatientMicroNutritionalValue,
    PatientTotalMacroNutritionalValue,
    PatientTotalMicroNutritionalValue,
)
from .patient_medical_history import PatientMedicalHistory
from .patient_permission import PatientPermission
from .patient_prescription import PatientPrescription
from .patient_sleep_habit import PatientSleepHabit
from .patient_smbg import PatientSMBG
from .patient_smoking_habit import PatientSmokingHabit
from .patient_token_usage_log import PatientTokenUsageLog
from .patient_vital import PatientVital
from .patient import Patient
from .patient_sleep import PatientSleep
