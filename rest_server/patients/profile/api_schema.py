from lib.schemas.patient import CompletePatientProfile, Patient
from rest_server.response_models import SuccessResponse


PatientCompleteProfileResponse = SuccessResponse[CompletePatientProfile]

PatientProfileResponse = SuccessResponse[Patient]
