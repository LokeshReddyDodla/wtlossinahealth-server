from lib.schemas.patient import PatientDiabeticHistorySchema
from lib.schemas.patient_meal import PatientMeal


class PatientMealSchema(PatientMeal):
    patient: PatientDiabeticHistorySchema
