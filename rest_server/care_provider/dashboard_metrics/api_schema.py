from lib.schemas.patient_meal import PatientMeal
from lib.schemas.patient import Patient as PatientSchema


class PatientMealSchema(PatientMeal):
    patient: PatientSchema
